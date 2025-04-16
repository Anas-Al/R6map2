import discord
from discord.ext import commands
from discord import app_commands
import os
import random
import asyncio
import json
from collections import defaultdict

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

MAPS_FOLDER = "."
MMR_FILE = "mmr.json"
queue = []
votes = defaultdict(int)
voters = set()
captains = []
PICKS = []
voting_in_progress = False
mmr_data = {}
results_channel_id = None
game_number = 1
active_game_data = {}

# Load and save MMR
def load_mmr():
    global mmr_data
    if os.path.exists(MMR_FILE):
        with open(MMR_FILE, "r") as f:
            mmr_data = json.load(f)

def save_mmr():
    with open(MMR_FILE, "w") as f:
        json.dump(mmr_data, f, indent=4)

def update_leaderboard():
    leaderboard = sorted(mmr_data.items(), key=lambda x: x[1], reverse=True)
    lines = [f"**{i+1}.** <@{uid}> — **{mmr}** MMR" for i, (uid, mmr) in enumerate(leaderboard[:10])]
    return "\n".join(lines)

@bot.event
async def on_ready():
    load_mmr()
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.content.lower() == "!coinflip":
        result = random.choice(["Heads", "Tails"])
        await message.channel.send(f"🪙 The coin landed on **{result}**!")
    elif message.content.lower() == "!r6map":
        map_images = [f for f in os.listdir(MAPS_FOLDER) if f.endswith(('.png', '.jpg', '.jpeg'))]
        if not map_images:
            await message.channel.send("❌ No map images found.")
            return
        selected_map = random.choice(map_images)
        map_name = os.path.splitext(selected_map)[0].replace('_', ' ').title()
        with open(os.path.join(MAPS_FOLDER, selected_map), 'rb') as f:
            picture = discord.File(f)
            await message.channel.send(f"🗺️ Random Map: **{map_name}**", file=picture)
    await bot.process_commands(message)

class QueueView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Join Queue", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        global voting_in_progress
        user = interaction.user
        if user in queue:
            await interaction.response.send_message("You're already in the queue.", ephemeral=True)
            return
        queue.append(user)
        await interaction.response.send_message(f"{user.display_name} joined the queue! ({len(queue)}/10)", ephemeral=True)
        if len(queue) == 10 and not voting_in_progress:
            await start_game(interaction.guild)

    @discord.ui.button(label="Leave Queue", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user not in queue:
            await interaction.response.send_message("You're not in the queue.", ephemeral=True)
            return
        queue.remove(user)
        await interaction.response.send_message(f"{user.display_name} left the queue. ({len(queue)}/10)", ephemeral=True)

@tree.command(name="setupqueue", description="Post the Tuah Tenmans queue panel.")
async def setupqueue(interaction: discord.Interaction):
    embed = discord.Embed(title="Tuah Tenmans Queue", description="Click to join or leave the 10mans queue.", color=0x00ffcc)
    embed.set_footer(text="Tuah Tenmans")
    await interaction.channel.send(embed=embed, view=QueueView())
    await interaction.response.send_message("Queue panel created.", ephemeral=True)

@tree.command(name="forcestart", description="Force start a match even if less than 10 players are queued.")
async def forcestart(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You don't have permission to force start.", ephemeral=True)
        return
    if len(queue) < 2:
        await interaction.response.send_message("Not enough players to start.", ephemeral=True)
        return
    await start_game(interaction.guild, force=True)
    await interaction.response.send_message("Force started match.", ephemeral=True)

@tree.command(name="results", description="Set this channel to receive match result logs.")
async def set_results_channel(interaction: discord.Interaction):
    global results_channel_id
    results_channel_id = interaction.channel.id
    await interaction.response.send_message("This channel will now receive Tuah Tenmans results.", ephemeral=True)

async def start_game(guild, force=False):
    global voting_in_progress, game_number, active_game_data
    voting_in_progress = True
    players = queue.copy()
    if not force and len(players) != 10:
        return
    category = discord.utils.get(guild.categories, name="Tuah Tenmans")
    if not category:
        category = await guild.create_category("Tuah Tenmans")
    text_channel = await guild.create_text_channel(f"game-{game_number}", category=category)
    await text_channel.set_permissions(guild.default_role, read_messages=False)
    for member in players:
        await text_channel.set_permissions(member, read_messages=True, send_messages=True)

    active_game_data["channel"] = text_channel
    active_game_data["players"] = players
    queue.clear()
    await text_channel.send(embed=discord.Embed(title="Tuah Tenmans - Captain Vote", description="Vote for 2 captains below!", color=0x3498db).set_footer(text="Tuah Tenmans"))
    view = discord.ui.View(timeout=30)
    for p in players:
        view.add_item(CaptainVoteButton(p))
    await text_channel.send(view=view)

class CaptainVoteButton(discord.ui.Button):
    def __init__(self, user):
        super().__init__(label=user.display_name, style=discord.ButtonStyle.primary)
        self.user = user

    async def callback(self, interaction: discord.Interaction):
        if interaction.user in voters:
            await interaction.response.send_message("You've already voted.", ephemeral=True)
            return
        votes[self.user.id] += 1
        voters.add(interaction.user)
        await interaction.response.send_message(f"You voted for {self.user.display_name}.", ephemeral=True)

# Additional logic for pick phase, voice channels, winner voting, MMR, cancel voting, and cleanup
# will continue in next code block (file too large for one block)async def start_pick_phase(channel):
    async def start_pick_phase(channel):
    global PICKS, captains
    PICKS = [[], []]
    sorted_votes = sorted(votes.items(), key=lambda x: x[1], reverse=True)
    voters.clear()
    votes.clear()

    captain_ids = [sorted_votes[0][0], sorted_votes[1][0]]
    all_players = active_game_data["players"]
    captains.clear()
    picks = all_players.copy()
    for uid in captain_ids:
        for user in all_players:
            if user.id == uid:
                captains.append(user)
                picks.remove(user)

    # ✅ This is the corrected line
    await channel.send(
        f"🏆 **Captains:** {captains[0].mention} and {captains[1].mention}",
        embed=discord.Embed().set_footer(text="Tuah Tenmans")
    )
    turn = 0
    while picks:
        captain = captains[turn % 2]
        await channel.send(f"{captain.mention}, please pick a player by @mentioning them.")
        def check(m): return m.author == captain and m.channel == channel
        try:
            msg = await bot.wait_for("message", timeout=60, check=check)
            if not msg.mentions or msg.mentions[0] not in picks:
                await channel.send("❌ Invalid pick.")
                continue
            choice = msg.mentions[0]
            PICKS[turn % 2].append(choice)
            picks.remove(choice)
            turn += 1
        except asyncio.TimeoutError:
            await channel.send("❌ Pick phase timed out.")
            return

    await channel.send(embed=discord.Embed(
        title="Tuah Tenmans - Teams",
        description=f"**Team 1 (Captain: {captains[0].display_name})**: {', '.join(p.display_name for p in PICKS[0])}\n"
                    f"**Team 2 (Captain: {captains[1].display_name})**: {', '.join(p.display_name for p in PICKS[1])}",
        color=0x00ffcc
    ).set_footer(text="Tuah Tenmans"))

    await create_voice_channels(channel.guild, PICKS[0], PICKS[1])
    await post_win_vote(channel)

async def create_voice_channels(guild, team1, team2):
    category = discord.utils.get(guild.categories, name="Tuah Tenmans")
    vc1 = await guild.create_voice_channel("Team 1 VC", category=category)
    vc2 = await guild.create_voice_channel("Team 2 VC", category=category)

    for member in team1 + [captains[0]]:
        await member.move_to(vc1)
    for member in team2 + [captains[1]]:
        await member.move_to(vc2)

    active_game_data["vc1"] = vc1
    active_game_data["vc2"] = vc2

async def post_win_vote(channel):
    view = discord.ui.View(timeout=None)
    view.add_item(WinVoteButton("Team 1"))
    view.add_item(WinVoteButton("Team 2"))
    active_game_data["win_votes"] = {"Team 1": set(), "Team 2": set()}
    await channel.send(embed=discord.Embed(
        title="Tuah Tenmans - Vote for Winning Team",
        description="Click below to vote for the winner. First team to 6 votes wins.",
        color=0x5865f2
    ).set_footer(text="Tuah Tenmans"), view=view)

class WinVoteButton(discord.ui.Button):
    def __init__(self, team_name):
        super().__init__(label=team_name, style=discord.ButtonStyle.success)
        self.team_name = team_name

    async def callback(self, interaction: discord.Interaction):
        team_votes = active_game_data["win_votes"]
        for team in team_votes:
            team_votes[team].discard(interaction.user.id)
        team_votes[self.team_name].add(interaction.user.id)
        if len(team_votes[self.team_name]) >= 6:
            await declare_winner(interaction.channel, self.team_name)
        else:
            await interaction.response.send_message(f"You voted for **{self.team_name}**.", ephemeral=True)

async def declare_winner(channel, winning_team_name):
    team_index = 0 if "1" in winning_team_name else 1
    winners = PICKS[team_index] + [captains[team_index]]
    losers = PICKS[1 - team_index] + [captains[1 - team_index]]

    for user in winners:
        mmr_data[str(user.id)] = mmr_data.get(str(user.id), 1000) + 25
    for user in losers:
        mmr_data[str(user.id)] = mmr_data.get(str(user.id), 1000) - 25
    save_mmr()

    await channel.send(embed=discord.Embed(
        title="Match Complete",
        description=f"**{winning_team_name} wins!** MMR updated.",
        color=0x2ecc71
    ).set_footer(text="Tuah Tenmans"))

    if results_channel_id:
        results_channel = bot.get_channel(results_channel_id)
        if results_channel:
            await results_channel.send(f"**{winning_team_name} won** Tuah Tenmans Game {game_number}")

    await cleanup_game()

@tree.command(name="cancel", description="Vote to cancel the current match.")
async def cancel(interaction: discord.Interaction):
    if "cancel_votes" not in active_game_data:
        active_game_data["cancel_votes"] = set()
    active_game_data["cancel_votes"].add(interaction.user.id)

    if len(active_game_data["cancel_votes"]) >= 6:
        await interaction.channel.send("❌ Match canceled by vote. Cleaning up...")
        await cleanup_game()
    else:
        await interaction.response.send_message(f"Your cancel vote was counted. ({len(active_game_data['cancel_votes'])}/6)", ephemeral=True)

async def cleanup_game():
    global voting_in_progress, game_number
    if "channel" in active_game_data:
        await active_game_data["channel"].delete()
    if "vc1" in active_game_data:
        await active_game_data["vc1"].delete()
    if "vc2" in active_game_data:
        await active_game_data["vc2"].delete()
    active_game_data.clear()
    voting_in_progress = False
    game_number += 1

bot.run(os.getenv("TOKEN"))