// Registers the /teams slash command in one Discord server. Run once, and again
// only if the command definition below changes:
//
//   DISCORD_BOT_TOKEN=$(pbpaste) DISCORD_GUILD_ID=<server id> \
//     node worker/scripts/register-discord-command.mjs
//
// The bot token is used only here, never stored in the repo or the Worker.
const APPLICATION_ID = "1568703389934817502";

const command = {
  name: "teams",
  description: "Split players into two balanced teams",
  type: 1,
  options: [
    {
      type: 3, // string
      name: "players",
      description: "In-game names, separated by commas",
      required: true,
      max_length: 1000,
    },
  ],
};

const token = process.env.DISCORD_BOT_TOKEN;
const guild = process.env.DISCORD_GUILD_ID;
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
    body: JSON.stringify([command]),
  },
);
const text = await response.text();
if (!response.ok) {
  console.error(`Discord returned HTTP ${response.status}: ${text}`);
  process.exit(1);
}
console.log(`Registered: ${JSON.parse(text).map((c) => "/" + c.name).join(", ")}`);
