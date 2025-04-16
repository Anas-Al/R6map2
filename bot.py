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

# === Globals ===
MAPS_FOLDER = "."
MMR_FILE = "mmr.json"
queue = []
votes = defaultdict(int)
voters = set()
captains = []
PICKS = []
voting_in_progress = False
game_number = 1
results_channel_id = None
leaderboard_channel_id = None
active_game_data = {}
player_stats = defaultdict(lambda: {"mmr": 1000, "wins": 0, "losses": 0})

# === Load/Save Functions ===
def load_mmr():
    global player_stats
    if os.path.exists(MMR_FILE):
        with open(MMR_FILE, "r") as f:
            player_stats = json.load(f)

def save_mmr():
    with open(MMR_FILE, "w") as f:
        json.dump(player_stats, f, indent=4)

# === Build Queue Embed ===
def build_queue_embed():
    description = f"**Queue ({len(queue)}/10):**\n" + "\n".join([p.mention for p in queue]) if queue else "No players yet."
    embed = discord.Embed(title="Tuah Tenmans Queue", description=description, color=0x00ffcc)
    embed.set_footer(text="Tuah Tenmans")
    return embed

# === Queue Buttons View ===
class QueueView(discord.ui.View):
    def __init__(self, message=None):
        super().__init__(timeout=None)
        self.message = message

    @discord.ui.button(label="Join Queue", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user in queue:
            await interaction.response.send_message("You're already in the queue!", ephemeral=True)
            return
        queue.append(user)
        await interaction.response.defer()
        if self.message:
            await self.message.edit(embed=build_queue_embed(), view=self)
        if len(queue) == 10 and not voting_in_progress:
            await start_game(interaction.guild)

    @discord.ui.button(label="Leave Queue", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user not in queue:
            await interaction.response.send_message("You're not in the queue.", ephemeral=True)
            return
        queue.remove(user)
        await interaction.response.defer()
        if self.message:
            await self.message.edit(embed=build_queue_embed(), view=self)

# === Bot Ready Event ===
@bot.event
async def on_ready():
    load_mmr()
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")

# === !coinflip and !r6map ===
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

# === Slash Command to Post Queue Panel ===
@tree.command(name="setupqueue", description="Post the Tuah Tenmans queue panel.")
async def setupqueue(interaction: discord.Interaction):
    view = QueueView()
    message = await interaction.channel.send(embed=build_queue_embed(), view=view)
    view.message = message
    await interaction.response.send_message("Queue panel posted!", ephemeral=True)
# === Start a Game ===
async def start_game(guild, force=False):
    global voting_in_progress, game_number, active_game_data
    voting_in_progress = True
    players = queue.copy()
    if not force and len(players) != 10:
        return

    # Create category if not exists
    category = discord.utils.get(guild.categories, name="Tuah Tenmans")
    if not category:
        category = await guild.create_category("Tuah Tenmans")

    # Create private text channel for the game
    text_channel = await guild.create_text_channel(f"game-{game_number}", category=category)
    await text_channel.set_permissions(guild.default_role, read_messages=False)
    for member in players:
        await text_channel.set_permissions(member, read_messages=True, send_messages=True)

    active_game_data = {
        "channel": text_channel,
        "players": players,
        "cancel_votes": set(),
        "win_votes": {"Team 1": set(), "Team 2": set()}
    }

    queue.clear()
    await text_channel.send(embed=discord.Embed(
        title="Tuah Tenmans - Captain Vote",
        description="Vote for 2 captains using the buttons below.",
        color=0x3498db
    ).set_footer(text="Tuah Tenmans"), view=CaptainVoteView(players))

# === Captain Vote Buttons ===
class CaptainVoteView(discord.ui.View):
    def __init__(self, players):
        super().__init__(timeout=30)
        self.players = players
        for p in players:
            self.add_item(CaptainVoteButton(p))

class CaptainVoteButton(discord.ui.Button):
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

# === Finish Captain Vote and Start Pick Phase ===
async def finish_vote_and_pick():
    global PICKS, captains
    channel = active_game_data["channel"]
    sorted_votes = sorted(votes.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_votes) < 2:
        await channel.send("❌ Not enough votes.")
        return

    PICKS = [[], []]
    voters.clear()
    votes.clear()
    captains.clear()

    captain_ids = [sorted_votes[0][0], sorted_votes[1][0]]
    all_players = active_game_data["players"]
    picks = all_players.copy()

    for uid in captain_ids:
        for user in all_players:
            if user.id == uid:
                captains.append(user)
                picks.remove(user)

    await channel.send(f"🏆 **Captains:** {captains[0].mention} and {captains[1].mention}",
                       embed=discord.Embed().set_footer(text="Tuah Tenmans"))

    turn = 0
    while picks:
        captain = captains[turn % 2]
        await channel.send(f"{captain.mention}, pick a player by @mention.")
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
            await channel.send("⏳ Pick phase timed out.")
            return

    await channel.send(embed=discord.Embed(
        title="Tuah Tenmans - Teams",
        description=f"**Team 1:** {', '.join(p.display_name for p in PICKS[0])}\n"
                    f"**Team 2:** {', '.join(p.display_name for p in PICKS[1])}",
        color=0x00ffcc
    ).set_footer(text="Tuah Tenmans"))
# === Create Voice Channels ===
async def create_voice_channels(guild):
    category = discord.utils.get(guild.categories, name="Tuah Tenmans")
    vc1 = await guild.create_voice_channel("Team 1 VC", category=category)
    vc2 = await guild.create_voice_channel("Team 2 VC", category=category)

    for member in PICKS[0] + [captains[0]]:
        await member.move_to(vc1)
    for member in PICKS[1] + [captains[1]]:
        await member.move_to(vc2)

    active_game_data["vc1"] = vc1
    active_game_data["vc2"] = vc2

# === Winner Vote View ===
class WinVoteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WinVoteButton("Team 1"))
        self.add_item(WinVoteButton("Team 2"))

class WinVoteButton(discord.ui.Button):
    def __init__(self, team_name):
        super().__init__(label=f"Vote {team_name}", style=discord.ButtonStyle.success)
        self.team_name = team_name

    async def callback(self, interaction: discord.Interaction):
        votes = active_game_data["win_votes"]
        for team in votes:
            votes[team].discard(interaction.user.id)
        votes[self.team_name].add(interaction.user.id)

        await interaction.response.send_message(f"You voted for **{self.team_name}**.", ephemeral=True)
        if len(votes[self.team_name]) >= 6:
            await declare_winner(interaction.channel, self.team_name)

# === Declare Winner ===
async def declare_winner(channel, team):
    winners = PICKS[0] + [captains[0]] if team == "Team 1" else PICKS[1] + [captains[1]]
    losers  = PICKS[1] + [captains[1]] if team == "Team 1" else PICKS[0] + [captains[0]]

    for user in winners:
        id = str(user.id)
        player_stats[id]["mmr"] = player_stats.get(id, {}).get("mmr", 1000) + 25
        player_stats[id]["wins"] = player_stats.get(id, {}).get("wins", 0) + 1

    for user in losers:
        id = str(user.id)
        player_stats[id]["mmr"] = player_stats.get(id, {}).get("mmr", 1000) - 25
        player_stats[id]["losses"] = player_stats.get(id, {}).get("losses", 0) + 1

    save_mmr()
    await channel.send(embed=discord.Embed(
        title="Match Complete",
        description=f"**{team} wins!** MMR and stats updated.",
        color=0x2ecc71
    ).set_footer(text="Tuah Tenmans"))

    if leaderboard_channel_id:
        await post_leaderboard(bot.get_channel(leaderboard_channel_id))

    await cleanup_game()

# === Cancel Voting ===
class CancelVoteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CancelButton())

class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel Match", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        voters = active_game_data["cancel_votes"]
        voters.add(interaction.user)
        channel = interaction.channel
        names = "\n".join(u.mention for u in voters)
        if len(voters) >= 6:
            await channel.send("❌ Match canceled by vote.")
            await cleanup_game()
        else:
            await channel.send(embed=discord.Embed(
                title="Cancel Vote",
                description=f"Votes to cancel: **{len(voters)}/6**\n{names}",
                color=0xe74c3c
            ).set_footer(text="Tuah Tenmans"))

# === Cleanup Function ===
async def cleanup_game():
    global voting_in_progress, game_number
    ch = active_game_data.get("channel")
    if ch: await ch.delete()
    for key in ["vc1", "vc2"]:
        if key in active_game_data:
            await active_game_data[key].delete()
    active_game_data.clear()
    voting_in_progress = False
    game_number += 1

# === Leaderboard Posting ===
async def post_leaderboard(channel):
    top = sorted(player_stats.items(), key=lambda x: x[1]["mmr"], reverse=True)[:10]
    desc = "\n".join(
        f"**{i+1}.** <@{uid}> — {data['mmr']} MMR | {data['wins']}W - {data['losses']}L"
        for i, (uid, data) in enumerate(top)
    )
    embed = discord.Embed(title="Tuah Tenmans Leaderboard", description=desc, color=0x7289da)
    embed.set_footer(text="Tuah Tenmans")
    await channel.send(embed=embed)
# === /forcestart ===
@tree.command(name="forcestart", description="Force start a match even with less than 10 players.")
async def forcestart(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You don’t have permission to use this.", ephemeral=True)
        return
    if len(queue) < 2:
        await interaction.response.send_message("Not enough players in queue (min 2).", ephemeral=True)
        return
    await start_game(interaction.guild, force=True)
    await interaction.response.send_message("✅ Match force started!", ephemeral=True)

# === /cancel ===
@tree.command(name="cancel", description="Start a cancel vote for the current match.")
async def cancel(interaction: discord.Interaction):
    if not active_game_data.get("channel"):
        await interaction.response.send_message("❌ No active game to cancel.", ephemeral=True)
        return
    await active_game_data["channel"].send(
        embed=discord.Embed(
            title="Vote to Cancel Match",
            description="Click below if you want to cancel this match. 6 votes required.",
            color=0xff0000
        ).set_footer(text="Tuah Tenmans"),
        view=CancelVoteView()
    )
    await interaction.response.send_message("Cancel vote initiated.", ephemeral=True)

# === /results ===
@tree.command(name="results", description="Set this channel to post match result logs.")
async def set_results_channel(interaction: discord.Interaction):
    global results_channel_id
    results_channel_id = interaction.channel.id
    await interaction.response.send_message("✅ This channel will now receive result logs.", ephemeral=True)

# === /leaderboard ===
@tree.command(name="leaderboard", description="Choose a channel to post leaderboard updates.")
async def leaderboard(interaction: discord.Interaction):
    class ChannelDropdown(discord.ui.Select):
        def __init__(self):
            options = [
                discord.SelectOption(label=ch.name, value=str(ch.id))
                for ch in interaction.guild.text_channels
            ]
            super().__init__(placeholder="Select a channel...", options=options)

        async def callback(self, i: discord.Interaction):
            global leaderboard_channel_id
            leaderboard_channel_id = int(self.values[0])
            await i.response.send_message(f"✅ Leaderboard will post in <#{leaderboard_channel_id}>", ephemeral=True)

    class ChannelSelectView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)
            self.add_item(ChannelDropdown())

    await interaction.response.send_message("Choose a channel to post leaderboard updates:", view=ChannelSelectView(), ephemeral=True)

# === BOT STARTUP ===
bot.run(os.getenv("TOKEN"))