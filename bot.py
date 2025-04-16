
import discord
import os
import random
from discord.ext import commands
from collections import defaultdict
import asyncio
import json

# Setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

MAPS_FOLDER = "."
queue = []
voting_in_progress = False
votes = defaultdict(int)
voters = set()
mmr_data = {}
PICKS = []
captains = []

MMR_FILE = "mmr.json"
LEADERBOARD_CHANNEL_ID = 1362026327796093168  # Replace with your channel ID


def save_mmr():
    with open(MMR_FILE, "w") as f:
        json.dump({k: v for k, v in mmr_data.items()}, f, indent=4)


def load_mmr():
    global mmr_data
    if os.path.exists(MMR_FILE):
        with open(MMR_FILE, "r") as f:
            mmr_data = json.load(f)


def update_leaderboard(channel):
    leaderboard = sorted(mmr_data.items(), key=lambda x: x[1], reverse=True)
    lines = [f"**{i+1}.** <@{uid}> — **{mmr}** MMR" for i, (uid, mmr) in enumerate(leaderboard[:10])]
    return "\n".join(lines)


@bot.event
async def on_ready():
    load_mmr()
    print(f"✅ Logged in as {bot.user}")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.content.lower() == "!r6map":
        map_images = [f for f in os.listdir(MAPS_FOLDER) if f.endswith(('.png', '.jpg', '.jpeg'))]
        if not map_images:
            await message.channel.send("❌ No map images found.")
            return

        selected_map = random.choice(map_images)
        map_name = os.path.splitext(selected_map)[0].replace('_', ' ').title()
        with open(os.path.join(MAPS_FOLDER, selected_map), 'rb') as f:
            picture = discord.File(f)
            await message.channel.send(f"🗺️ Random Map: **{map_name}**", file=picture)

    if message.content.lower() == "!coinflip":
        result = random.choice(["Heads", "Tails"])
        await message.channel.send(f"🪙 The coin landed on **{result}**!")

    await bot.process_commands(message)


class QueueView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Join 10mans", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        global voting_in_progress
        user = interaction.user

        if user in queue:
            await interaction.response.send_message("You're already in the queue!", ephemeral=True)
            return

        queue.append(user)
        await interaction.response.send_message(f"✅ {user.display_name} joined the queue! ({len(queue)}/10)", ephemeral=True)

        if len(queue) == 10 and not voting_in_progress:
            voting_in_progress = True
            await start_captain_vote(interaction.channel)

    @discord.ui.button(label="Leave 10mans", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user not in queue:
            await interaction.response.send_message("You're not in the queue.", ephemeral=True)
            return
        queue.remove(user)
        await interaction.response.send_message(f"❌ {user.display_name} left the queue. ({len(queue)}/10)", ephemeral=True)


class VotingView(discord.ui.View):
    def __init__(self, players):
        super().__init__(timeout=30)
        for p in players:
            self.add_item(VoteButton(p))


class VoteButton(discord.ui.Button):
    def __init__(self, user):
        super().__init__(label=user.display_name, style=discord.ButtonStyle.primary)
        self.user = user

    async def callback(self, interaction: discord.Interaction):
        if interaction.user in voters:
            await interaction.response.send_message("You've already voted!", ephemeral=True)
            return

        votes[self.user.id] += 1
        voters.add(interaction.user)
        await interaction.response.send_message(f"You voted for {self.user.display_name}!", ephemeral=True)


async def start_captain_vote(channel):
    global votes, voters, captains
    votes.clear()
    voters.clear()

    player_names = "\n".join(f"- {p.display_name}" for p in queue)
    await channel.send(
        "**Queue filled! Vote for 2 captains using the buttons below:**\n\n"
        f"**Players:**\n{player_names}",
        view=VotingView(queue)
    )

    await asyncio.sleep(30)

    sorted_votes = sorted(votes.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_votes) < 2:
        await channel.send("❌ Not enough votes.")
        return

    captain_ids = [sorted_votes[0][0], sorted_votes[1][0]]
    captains.clear()
    picks = queue.copy()
    for uid in captain_ids:
        for user in queue:
            if user.id == uid:
                captains.append(user)
                picks.remove(user)

    await channel.send(f"🏆 **Captains:** {captains[0].mention} and {captains[1].mention}")
    await start_pick_phase(channel, picks)


async def start_pick_phase(channel, picks):
    global PICKS
    PICKS = [[], []]
    turn = 0
    while picks:
        current_captain = captains[turn % 2]

        def check(m):
            return m.author == current_captain and m.channel == channel

        await channel.send(f"{current_captain.mention}, pick a player by mentioning them.")

        try:
            msg = await bot.wait_for('message', timeout=60, check=check)
            mention = msg.mentions[0] if msg.mentions else None
            if mention not in picks:
                await channel.send("❌ Invalid pick.")
                continue
            PICKS[turn % 2].append(mention)
            picks.remove(mention)
            turn += 1
        except asyncio.TimeoutError:
            await channel.send("❌ Pick phase timed out.")
            return

    await channel.send(f"**Teams are set!**\n"
                       f"**{captains[0].display_name}'s Team:** {', '.join(p.display_name for p in PICKS[0])}\n"
                       f"**{captains[1].display_name}'s Team:** {', '.join(p.display_name for p in PICKS[1])}")
    queue.clear()
    global voting_in_progress
    voting_in_progress = False


@bot.command()
async def tenmans(ctx):
    await ctx.send("Click below to join or leave the 10mans queue:", view=QueueView())


@bot.command()
async def report(ctx, winner: int):
    if not captains or not PICKS:
        await ctx.send("❌ No match to report.")
        return

    team_winner = PICKS[winner - 1]
    team_loser = PICKS[1 if winner == 1 else 0]

    for user in team_winner + [captains[winner - 1]]:
        mmr_data[str(user.id)] = mmr_data.get(str(user.id), 1000) + 25
    for user in team_loser + [captains[1 if winner == 1 else 0]]:
        mmr_data[str(user.id)] = mmr_data.get(str(user.id), 1000) - 25

    save_mmr()

    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel:
        leaderboard_msg = update_leaderboard(channel)
        await channel.send("**Updated Leaderboard:**\n" + leaderboard_msg)

    await ctx.send("✅ MMR updated.")


@bot.command()
async def leaderboard(ctx):
    leaderboard_msg = update_leaderboard(ctx.channel)
    await ctx.send("**Leaderboard:**\n" + leaderboard_msg)


bot.run(os.getenv("TOKEN"))