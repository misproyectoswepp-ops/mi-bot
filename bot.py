import discord
from discord import app_commands
import os
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ── Estado del Anti-Raid ────────────────────────────────────
antiraid_config = {}                 # guild_id -> {"activo", "umbral", "ventana", "modo", "canal_alertas"}
antiraid_joins = defaultdict(list)   # guild_id -> [datetime, ...]
antiraid_emergencia = set()          # guild_ids actualmente en modo emergencia


@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot Anti-Raid conectado como: {client.user}")
    await client.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="🛡️ posibles raids"
    ))


async def _activar_emergencia(guild: discord.Guild, raid_cfg: dict):
    gid = guild.id
    canal_alertas = client.get_channel(raid_cfg.get("canal_alertas"))
    modo = raid_cfg["modo"]

    if modo == "lock":
        try:
            await guild.edit(verification_level=discord.VerificationLevel.high)
        except discord.Forbidden:
            pass

    if canal_alertas:
        accion_texto = (
            "Se expulsarán automáticamente las cuentas nuevas (menos de 7 días) "
            "que se unan mientras dure la alerta."
            if modo == "kick" else
            "Se activó temporalmente el nivel de verificación alto del servidor."
        )
        embed = discord.Embed(
            title="🚨 Posible Raid Detectado",
            description=f"Se detectaron **{raid_cfg['umbral']}** ingresos en los últimos **{raid_cfg['ventana']}** segundos.",
            color=discord.Color.dark_red()
        )
        embed.add_field(name="Acción tomada", value=accion_texto, inline=False)
        embed.set_footer(text=f"Modo emergencia activo por {raid_cfg['ventana'] * 6} segundos")
        await canal_alertas.send(embed=embed)

    await asyncio.sleep(raid_cfg["ventana"] * 6)
    antiraid_emergencia.discard(gid)

    if modo == "lock":
        try:
            await guild.edit(verification_level=discord.VerificationLevel.medium)
        except discord.Forbidden:
            pass

    if canal_alertas:
        await canal_alertas.send("✅ Anti-raid: modo de emergencia desactivado, el servidor volvió a la normalidad.")


@client.event
async def on_member_join(member: discord.Member):
    gid = member.guild.id
    raid_cfg = antiraid_config.get(gid)
    if not raid_cfg or not raid_cfg.get("activo"):
        return

    ahora = datetime.utcnow()
    ventana = raid_cfg["ventana"]

    antiraid_joins[gid].append(ahora)
    antiraid_joins[gid] = [
        ts for ts in antiraid_joins[gid] if (ahora - ts).total_seconds() <= ventana
    ]

    if len(antiraid_joins[gid]) >= raid_cfg["umbral"] and gid not in antiraid_emergencia:
        antiraid_emergencia.add(gid)
        asyncio.create_task(_activar_emergencia(member.guild, raid_cfg))

    if gid in antiraid_emergencia and raid_cfg["modo"] == "kick":
        edad_cuenta = ahora - member.created_at.replace(tzinfo=None)
        if edad_cuenta < timedelta(days=7):
            try:
                await member.kick(reason="Anti-raid: cuenta nueva durante raid detectado")
            except discord.Forbidden:
                pass


# ── Comandos ─────────────────────────────────────────────────
@tree.command(name="antiraid", description="Activa o desactiva la protección anti-raid")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    activar="True para activar, False para desactivar",
    umbral="Cantidad de ingresos para disparar la alerta (por defecto 5)",
    ventana="Ventana de tiempo en segundos para contar ingresos (por defecto 10)",
    modo="Acción a tomar durante el raid",
    canal_alertas="Canal donde enviar las alertas (por defecto, el canal actual)"
)
@app_commands.choices(modo=[
    app_commands.Choice(name="Expulsar cuentas nuevas", value="kick"),
    app_commands.Choice(name="Bloquear con verificación alta", value="lock"),
])
async def antiraid(
    interaction: discord.Interaction,
    activar: bool,
    umbral: int = 5,
    ventana: int = 10,
    modo: app_commands.Choice[str] = None,
    canal_alertas: discord.TextChannel = None
):
    gid = interaction.guild.id
    if activar:
        modo_valor = modo.value if modo else "kick"
        antiraid_config[gid] = {
            "activo": True,
            "umbral": umbral,
            "ventana": ventana,
            "modo": modo_valor,
            "canal_alertas": (canal_alertas or interaction.channel).id
        }
        await interaction.response.send_message(
            f"🛡️ Anti-raid activado. Umbral: **{umbral}** ingresos en **{ventana}** segundos. "
            f"Modo: **{modo_valor}**. Alertas en {(canal_alertas or interaction.channel).mention}",
            ephemeral=True
        )
    else:
        if gid in antiraid_config:
            antiraid_config[gid]["activo"] = False
        await interaction.response.send_message("❌ Anti-raid desactivado.", ephemeral=True)


@tree.command(name="raid-status", description="Muestra el estado actual del anti-raid")
async def raid_status(interaction: discord.Interaction):
    gid = interaction.guild.id
    raid_cfg = antiraid_config.get(gid)

    if not raid_cfg or not raid_cfg.get("activo"):
        await interaction.response.send_message("❌ El anti-raid está **desactivado** en este servidor.", ephemeral=True)
        return

    canal = client.get_channel(raid_cfg.get("canal_alertas"))
    emergencia = "🚨 SÍ, modo emergencia activo ahora mismo" if gid in antiraid_emergencia else "✅ No"

    embed = discord.Embed(title="🛡️ Estado del Anti-Raid", color=discord.Color.blurple())
    embed.add_field(name="Umbral", value=f"{raid_cfg['umbral']} ingresos", inline=True)
    embed.add_field(name="Ventana", value=f"{raid_cfg['ventana']} segundos", inline=True)
    embed.add_field(name="Modo", value=raid_cfg["modo"], inline=True)
    embed.add_field(name="Canal de alertas", value=canal.mention if canal else "No configurado", inline=False)
    embed.add_field(name="¿Emergencia activa?", value=emergencia, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


TOKEN = os.getenv("DISCORD_TOKEN")
client.run(TOKEN)
