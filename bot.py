import os
import json
from pathlib import Path
import discord
from discord.ext import commands
from dotenv import load_dotenv
from discord import app_commands
import asyncpg

# === CONFIGURATION ===
# Set your vouch channel ID and points per picture.
VOUCH_CHANNEL_ID = 1426271314792157346  # Replace with your vouch channel ID
POINTS_PER_PICTURE = 1  # Change how many points per picture if you want
PROVIDER_ROLE_NAME = "Provider"  # Only award points if a tagged member has this role

# Load token from environment variable. Do NOT hardcode tokens in code.
# Also support a local .env file for development.
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")


# === BOT SETUP ===
intents = discord.Intents.default()
intents.message_content = True  # Also enable Message Content Intent in the Dev Portal
bot = commands.Bot(command_prefix="!", intents=intents)


"""
Storage layer: Postgres on Railway, JSON locally.
"""

DATA_PATH = Path(__file__).with_name("vouches.json")


class JsonStorage:
    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path
        # Structure: { user_id: {"points": int, "total_vouches": int} }
        self._data: dict[str, dict[str, int]] = {}

    async def init(self) -> None:
        if self.data_path.exists():
            try:
                loaded = json.loads(self.data_path.read_text(encoding="utf-8"))
                # Migrate from { user_id: points_int } to structured objects
                if isinstance(loaded, dict):
                    migrated: dict[str, dict[str, int]] = {}
                    for k, v in loaded.items():
                        if isinstance(v, int):
                            migrated[str(k)] = {"points": int(v), "total_vouches": 0}
                        elif isinstance(v, dict):
                            points_val = int(v.get("points", v.get("score", 0)))
                            vouches_val = int(v.get("total_vouches", 0))
                            migrated[str(k)] = {"points": points_val, "total_vouches": vouches_val}
                    self._data = migrated
                else:
                    self._data = {}
            except Exception:
                self._data = {}
        else:
            self._data = {}

    async def get_points(self, user_id: int) -> int:
        entry = self._data.get(str(user_id))
        if not entry:
            return 0
        return int(entry.get("points", 0))

    async def get_stats(self, user_id: int) -> tuple[int, int]:
        entry = self._data.get(str(user_id))
        if not entry:
            return 0, 0
        return int(entry.get("points", 0)), int(entry.get("total_vouches", 0))

    async def add_points(self, user_id: int, delta: int) -> int:
        uid = str(user_id)
        entry = self._data.get(uid) or {"points": 0, "total_vouches": 0}
        new_total = int(entry.get("points", 0)) + int(delta)
        if new_total < 0:
            new_total = 0
        entry["points"] = new_total
        self._data[uid] = entry
        self.data_path.write_text(
            json.dumps(self._data, indent=4, ensure_ascii=False), encoding="utf-8"
        )
        return new_total

    async def add_vouch(self, user_id: int, points_delta: int, vouches_delta: int = 1) -> tuple[int, int]:
        uid = str(user_id)
        entry = self._data.get(uid) or {"points": 0, "total_vouches": 0}
        new_points = int(entry.get("points", 0)) + int(points_delta)
        if new_points < 0:
            new_points = 0
        new_vouches = int(entry.get("total_vouches", 0)) + int(vouches_delta)
        if new_vouches < 0:
            new_vouches = 0
        entry["points"] = new_points
        entry["total_vouches"] = new_vouches
        self._data[uid] = entry
        self.data_path.write_text(
            json.dumps(self._data, indent=4, ensure_ascii=False), encoding="utf-8"
        )
        return new_points, new_vouches

    async def top(self, limit: int = 10) -> list[tuple[int, int]]:
        # Sort by points descending
        items = sorted(
            self._data.items(),
            key=lambda item: int(item[1].get("points", 0)),
            reverse=True,
        )[:limit]
        return [(int(uid), int(obj.get("points", 0))) for uid, obj in items]


class PostgresStorage:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.pool: asyncpg.pool.Pool | None = None

    async def init(self) -> None:
        # Railway often provides DATABASE_URL; SSL may be required. Using default SSL context when available.
        self.pool = await asyncpg.create_pool(self.database_url)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                create table if not exists vouches (
                    user_id bigint primary key,
                    points integer not null default 0,
                    total_vouches integer not null default 0
                );
                """
            )
            # Ensure column exists for older deployments
            await conn.execute(
                """
                alter table if exists vouches
                add column if not exists total_vouches integer not null default 0;
                """
            )

    async def get_points(self, user_id: int) -> int:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "select points from vouches where user_id = $1", int(user_id)
            )
            return int(row["points"]) if row else 0

    async def get_stats(self, user_id: int) -> tuple[int, int]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "select points, total_vouches from vouches where user_id = $1",
                int(user_id),
            )
            if not row:
                return 0, 0
            return int(row["points"]), int(row["total_vouches"])

    async def add_points(self, user_id: int, delta: int) -> int:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                insert into vouches as v(user_id, points)
                values($1, 0)
                on conflict (user_id)
                do update set points = greatest(0, v.points + $2)
                returning points
                """,
                int(user_id), int(delta)
            )
            return int(row["points"]) if row else 0

    async def add_vouch(self, user_id: int, points_delta: int, vouches_delta: int = 1) -> tuple[int, int]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                insert into vouches as v(user_id, points, total_vouches)
                values($1, 0, 0)
                on conflict (user_id)
                do update set
                    points = greatest(0, v.points + $2),
                    total_vouches = greatest(0, v.total_vouches + $3)
                returning points, total_vouches
                """,
                int(user_id), int(points_delta), int(vouches_delta)
            )
            return (int(row["points"]), int(row["total_vouches"])) if row else (0, 0)

    async def top(self, limit: int = 10) -> list[tuple[int, int]]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "select user_id, points from vouches order by points desc limit $1",
                int(limit),
            )
        return [(int(r["user_id"]), int(r["points"])) for r in rows]


# Choose storage based on environment (DATABASE_URL => Postgres, else JSON)
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
storage: PostgresStorage | JsonStorage
if DATABASE_URL:
    storage = PostgresStorage(DATABASE_URL)
else:
    storage = JsonStorage(DATA_PATH)


# === EVENTS ===
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    # ensure storage is initialized
    try:
        await storage.init()
    except Exception as e:
        print(f"Storage init failed: {e}")
    # Sync application (slash) commands
    try:
        synced = await bot.tree.sync()
        print(f"🔁 Synced {len(synced)} app command(s)")
    except Exception as e:
        print(f"App command sync failed: {e}")


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

        # Require that the message tags at least one member who has the Provider role
        has_provider_tag = False
        if message.guild is not None and message.mentions:
            provider_role = next((r for r in message.guild.roles if r.name == PROVIDER_ROLE_NAME), None)
            if provider_role is not None:
                has_provider_tag = any(provider_role in m.roles for m in message.mentions)

        if image_attachments and has_provider_tag:
            try:
                earned_points = POINTS_PER_PICTURE * len(image_attachments)
                # Atomically increment points and vouch count
                if hasattr(storage, "add_vouch"):
                    new_total, new_vouches = await storage.add_vouch(
                        int(message.author.id), earned_points, 1
                    )
                else:
                    # Fallback for older storage implementation
                    new_total = await storage.add_points(int(message.author.id), earned_points)
                    # Try best-effort to read vouches count if available
                    if hasattr(storage, "get_stats"):
                        _points, new_vouches = await storage.get_stats(int(message.author.id))
                    else:
                        new_vouches = 0
                try:
                    await message.add_reaction("✅")
                except Exception:
                    pass
                try:
                    await message.reply(
                        f"⭐ {message.author.mention} earned {earned_points} point(s). Total: {new_total} point(s). Total vouches: {new_vouches}."
                    )
                except Exception:
                    pass
            except Exception as e:
                print(f"Failed to save vouch points: {e}")
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
    if hasattr(storage, "get_stats"):
        points, total_vouches = await storage.get_stats(int(member.id))
    else:
        points = await storage.get_points(int(member.id))
        total_vouches = 0
    await ctx.send(
        f"⭐ {member.display_name} has {points} point(s) • {total_vouches} total vouch(es)."
    )


@bot.command()
async def topvouches(ctx: commands.Context):
    """Show the top 10 users with the most vouches."""
    top_list = await storage.top(10)

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


@bot.command()
@commands.has_permissions(manage_guild=True)
async def addvouch(ctx: commands.Context, member: discord.Member, amount: int = 1):
    """Add vouch points to a member (mods only)."""
    if amount < 1:
        await ctx.send("Amount must be at least 1.")
        return
    if hasattr(storage, "add_vouch"):
        new_total, new_vouches = await storage.add_vouch(int(member.id), amount, 1)
        await ctx.send(
            f"✅ Added {amount} to {member.display_name}. Total: {new_total} • Vouches: {new_vouches}"
        )
    else:
        new_total = await storage.add_points(int(member.id), amount)
        await ctx.send(f"✅ Added {amount} to {member.display_name}. Total: {new_total}")


@bot.command()
@commands.has_permissions(manage_guild=True)
async def removevouch(ctx: commands.Context, member: discord.Member, amount: int = 1):
    """Remove vouch points from a member (mods only)."""
    if amount < 1:
        await ctx.send("Amount must be at least 1.")
        return
    new_total = await storage.add_points(int(member.id), -amount)
    if hasattr(storage, "get_stats"):
        _p, vouches = await storage.get_stats(int(member.id))
        await ctx.send(
            f"🗑️ Removed {amount} from {member.display_name}. Total: {new_total} • Vouches: {vouches}"
        )
    else:
        await ctx.send(f"🗑️ Removed {amount} from {member.display_name}. Total: {new_total}")


# === SLASH COMMANDS ===
@bot.tree.command(name="vouches", description="Check your or someone else's vouch points.")
async def slash_vouches(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user  # type: ignore[assignment]
    if hasattr(storage, "get_stats"):
        points, total_vouches = await storage.get_stats(int(member.id))
    else:
        points = await storage.get_points(int(member.id))
        total_vouches = 0
    await interaction.response.send_message(
        f"⭐ {member.display_name} has {points} point(s) • {total_vouches} total vouch(es)."
    )


@bot.tree.command(name="topvouches", description="Show the top 10 users with the most vouches.")
async def slash_topvouches(interaction: discord.Interaction):
    top_list = await storage.top(10)

    embed = discord.Embed(
        title="🏆 Top Vouch Leaderboard",
        description="Here are the top users with the most vouch points!",
        color=discord.Color.gold(),
    )

    rank = 1
    for user_id, points in top_list:
        display_name = None
        member = interaction.guild.get_member(int(user_id))
        if member is None:
            try:
                member = await interaction.guild.fetch_member(int(user_id))
            except Exception:
                member = None
        display_name = member.display_name if member is not None else "(User Left Server)"

        embed.add_field(
            name=f"#{rank} {display_name}",
            value=f"⭐ {points} point(s)",
            inline=False,
        )
        rank += 1

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="addvouch", description="Add vouch points to a member (mods only).")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(member="Member to add points to", amount="How many points to add")
async def slash_addvouch(interaction: discord.Interaction, member: discord.Member, amount: int = 1):
    if amount < 1:
        await interaction.response.send_message("Amount must be at least 1.", ephemeral=True)
        return
    if hasattr(storage, "add_vouch"):
        new_total, new_vouches = await storage.add_vouch(int(member.id), amount, 1)
        msg = f"✅ Added {amount} to {member.display_name}. Total: {new_total} • Vouches: {new_vouches}"
    else:
        new_total = await storage.add_points(int(member.id), amount)
        msg = f"✅ Added {amount} to {member.display_name}. Total: {new_total}"
    await interaction.response.send_message(msg)


@bot.tree.command(name="removevouch", description="Remove vouch points from a member (mods only).")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(member="Member to remove points from", amount="How many points to remove")
async def slash_removevouch(interaction: discord.Interaction, member: discord.Member, amount: int = 1):
    if amount < 1:
        await interaction.response.send_message("Amount must be at least 1.", ephemeral=True)
        return
    # Removing points should not remove vouch count
    new_total = await storage.add_points(int(member.id), -amount)
    if hasattr(storage, "get_stats"):
        _p, vouches = await storage.get_stats(int(member.id))
        msg = f"🗑️ Removed {amount} from {member.display_name}. Total: {new_total} • Vouches: {vouches}"
    else:
        msg = f"🗑️ Removed {amount} from {member.display_name}. Total: {new_total}"
    await interaction.response.send_message(msg)


# === RUN THE BOT ===
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN environment variable is not set. Set it before running the bot."
        )
    bot.run(TOKEN)


