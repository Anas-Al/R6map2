from keep_alive import keep_alive
import discord
import os
import random

# Enable basic message intents
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

MAPS_FOLDER = "./maps"


@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.lower() == "!r6map":
        map_images = [
            f for f in os.listdir(MAPS_FOLDER)
            if f.endswith(('.png', '.jpg', '.jpeg'))
        ]
        print("Images found:", map_images)  # Debugging

        if not map_images:
            await message.channel.send("❌ No map images found.")
            return

        selected_map = random.choice(map_images)
        map_name = os.path.splitext(selected_map)[0].replace('_', ' ').title()

        with open(os.path.join(MAPS_FOLDER, selected_map), 'rb') as f:
            picture = discord.File(f)
            await message.channel.send(f"🗺️ Random Map: **{map_name}**",
                                       file=picture)
    if message.content.lower() == "!lowf":
        with open("lowf.jpg", "rb") as f:
            file = discord.File(f)
            await message.channel.send("lowf is a retard", file=file)
    if message.content.lower() == "!dash":
        with open("dash.jpg", "rb") as f:
            file = discord.File(f)
            await message.channel.send("6'8 280 and rich", file=file)


# Replace with your bot token
# Existing code above...

from keep_alive import keep_alive
import time

keep_alive()

while True:
    try:
        client.run(os.getenv("TOKEN"))
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
        print("🔁 Restarting in 5 seconds...")
        time.sleep(5)

