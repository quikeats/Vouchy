import os
import json
from pathlib import Path
import discord
from discord.ext import commands
from dotenv import load_dotenv

# === CONFIGURATION ===
# Set your vouch channel ID and points per picture.
VOUCH_CHANNEL_ID = 1426271314792157346  # Replace with your vouch channel ID
POINTS_PER_PICTURE = 1  # Change how many points per picture if you want

# Load token from environment variable. Do NOT hardcode tokens in code.
# Also support a local .env file for development.
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")


# === BOT SETUP ===
intents = discord.Intents.default()
intents.message_content = True  # Also enable Message Content Intent in the Dev Portal
bot = commands.Bot(command_prefix="!", intents=intents)


# === DATA STORAGE ===
DATA_PATH = Path(__file__).with_name("vouches.json")

def _load_data() -> dict:
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

vouches: dict[str, int] = _load_data()

def save_data() -> None:
    """Persist vouch data to a JSON file next to the script."""
    DATA_PATH.write_text(json.dumps(vouches, indent=4, ensure_ascii=False), encoding="utf-8")


# === EVENTS ===
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Only track messages in the vouch channel
    if message.channel.id == VOUCH_CHANNEL_ID:
        image_attachments = [
            a for a in message.attachments
            if (a.content_type and a.content_type.startswith("image/"))
            or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
        ]

        if image_attachments:
            user_id = str(message.author.id)
            current_points = vouches.get(user_id, 0)
            vouches[user_id] = current_points + POINTS_PER_PICTURE * len(image_attachments)
            save_data()
            try:
                await message.add_reaction("✅")
            except Exception:
                pass

    await bot.process_commands(message)


# === COMMANDS ===
@bot.command(name="vouches")
async def vouches_cmd(ctx: commands.Context, member: discord.Member | None = None):
    """Check your or someone else's vouch points."""
    member = member or ctx.author
    user_id = str(member.id)
    points = vouches.get(user_id, 0)
    await ctx.send(f"⭐ {member.display_name} has {points} vouch point(s)!")


@bot.command()
async def topvouches(ctx: commands.Context):
    """Show the top 10 users with the most vouches."""
    if not vouches:
        await ctx.send("📉 No vouches recorded yet.")
        return

    # Sort by total points
    sorted_vouches = sorted(vouches.items(), key=lambda item: item[1], reverse=True)
    top_list = sorted_vouches[:10]

    embed = discord.Embed(
        title="🏆 Top Vouch Leaderboard",
        description="Here are the top users with the most vouch points!",
        color=discord.Color.gold(),
    )

    rank = 1
    for user_id, points in top_list:
        display_name = None
        member = ctx.guild.get_member(int(user_id)) if ctx.guild else None
        if member is None and ctx.guild is not None:
            try:
                member = await ctx.guild.fetch_member(int(user_id))
            except Exception:
                member = None
        if member is not None:
            display_name = member.display_name
        else:
            display_name = "(User Left Server)"

        embed.add_field(
            name=f"#{rank} {display_name}",
            value=f"⭐ {points} point(s)",
            inline=False,
        )
        rank += 1

    await ctx.send(embed=embed)


# === RUN THE BOT ===
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN environment variable is not set. Set it before running the bot."
        )
    bot.run(TOKEN)


