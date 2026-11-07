// Registers the /teams and /server slash commands in one Discord server. Run once, and again
// only if the command definition below changes:
//
//   DISCORD_BOT_TOKEN=$(pbpaste) node worker/scripts/register-discord-command.mjs
//
// Set DISCORD_GUILD_ID to register in a different server.
//
// The bot token is used only here, never stored in the repo or the Worker.
const APPLICATION_ID = "1568703389934817502";
const DEFAULT_GUILD_ID = "698372700829253672"; // the CS2 Nights server

const teams = {
  name: "teams",
  description: "Split players into two balanced teams",
  type: 1,
  options: [
    {
      type: 3, // string
      name: "players",
      description: "Optional: type names (comma-separated) instead of picking from a list",
      required: false,
      max_length: 1000,
    },
  ],
};

const SUBCOMMAND = 1;
const server = {
  name: "server",
  description: "Control the CS2 server",
  type: 1,
  default_member_permissions: String(1 << 5), // Manage Server; the Worker re-checks
  contexts: [0], // servers only, not DMs
  options: [
    { type: SUBCOMMAND, name: "start", description: "Start the game server" },
    { type: SUBCOMMAND, name: "stop", description: "Stop the game server (asks to confirm)" },
    { type: SUBCOMMAND, name: "restart-game", description: "Restart the match, scores reset to 0-0 (asks to confirm)" },
    {
      type: SUBCOMMAND,
      name: "map",
      description: "Change the map",
      options: [
        {
          type: 3,
          name: "name",
          description: "Start typing a map name",
          required: true,
          autocomplete: true,
        },
      ],
    },
    { type: SUBCOMMAND, name: "warmup-end", description: "End warmup now" },
    { type: SUBCOMMAND, name: "forcecamera", description: "Dead players can only spectate their own team" },
  ],
};

const commands = [teams, server];

const token = process.env.DISCORD_BOT_TOKEN;
const guild = process.env.DISCORD_GUILD_ID || DEFAULT_GUILD_ID;
if (!token || !/^\d{17,20}$/.test(guild || "")) {
  console.error("Set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID (the numeric server ID).");
  process.exit(1);
}

const response = await fetch(
  `https://discord.com/api/v10/applications/${APPLICATION_ID}/guilds/${guild}/commands`,
  {
    method: "PUT", // replaces this app's commands in the server with exactly this list
    headers: {
      Authorization: `Bot ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(commands),
  },
);
const text = await response.text();
if (!response.ok) {
  console.error(`Discord returned HTTP ${response.status}: ${text}`);
  process.exit(1);
}
console.log(`Registered: ${JSON.parse(text).map((c) => "/" + c.name).join(", ")}`);
