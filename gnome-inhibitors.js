#!/usr/bin/env bun

const { execSync } = require('child_process');
const dbus = require('dbus-next');

/**
 * GNOME Session Inhibitor Manager
 * Find and display active inhibitors preventing suspend/sleep
 */
async function main() {
  console.log("🔒 GNOME Session Inhibitors:");
  console.log("============================");

  try {
    // Connect to session bus
    const bus = dbus.sessionBus();
    const sessionManager = await bus.getProxyObject(
      'org.gnome.SessionManager',
      '/org/gnome/SessionManager'
    );
    const managerIface = sessionManager.getInterface('org.gnome.SessionManager');
    // Get all inhibitor object paths using GetInhibitors
    const inhibitorPaths = await managerIface.GetInhibitors();

    if (!inhibitorPaths || inhibitorPaths.length === 0) {
      console.log("No active inhibitors found.");
      process.exit(0);
    }

    // Loop through each inhibitor and get details
    for (const path of inhibitorPaths) {
      console.log(`Inhibitor: ${path}`);
      try {
        // Get proxy for inhibitor
        const inhibitorObj = await bus.getProxyObject('org.gnome.SessionManager', path);
        const inhibitorIface = inhibitorObj.getInterface('org.gnome.SessionManager.Inhibitor');
        // Get App ID
        const appId = await inhibitorIface.GetAppId();
        // Get reason
        const reason = await inhibitorIface.GetReason();
        // Get flags
        const flags = await inhibitorIface.GetFlags();
        // Interpret flags (bitmask)
        const flagStrings = [];
        if (flags & 1) flagStrings.push("logout");
        if (flags & 2) flagStrings.push("switch-user");
        if (flags & 4) flagStrings.push("suspend");
        if (flags & 8) flagStrings.push("idle");
        const flagText = flagStrings.join(", ");
        console.log(`  App ID: ${appId}`);
        console.log(`  Reason: ${reason}`);
        console.log(`  Flags: ${flags} (${flagText})`);
        // Get process information from systemd/logind for comparison
        console.log("\nComparing with systemd/logind inhibitors:");
        const logindOutput = execSync('systemd-inhibit --list').toString();
        const relevantLines = logindOutput.split('\n').filter(line => 
          line.includes(appId) || 
          (line.includes('sleep') && line.includes('inhibited'))
        );
        relevantLines.forEach(line => console.log(`    ${line}`));
      } catch (err) {
        console.error(`  Error fetching details for ${path}:`, err);
      }
    }
  } catch (err) {
    console.error("Error communicating with GNOME SessionManager:", err);
  }
  process.exit(0);
}

main();
