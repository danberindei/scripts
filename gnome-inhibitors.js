#!/usr/bin/env bun

const { execSync } = require('child_process');

/**
 * GNOME Session Inhibitor Manager
 * Find and display active inhibitors preventing suspend/sleep
 */
async function main() {
  console.log("🔒 GNOME Session Inhibitors:");
  console.log("============================");

  try {
    // Get all inhibitor object paths using GetInhibitors
    const inhibitorOutput = execSync(
      'gdbus call --session --dest org.gnome.SessionManager --object-path /org/gnome/SessionManager --method org.gnome.SessionManager.GetInhibitors'
    ).toString().trim();

    // Extract object paths with regex
    const objectPaths = inhibitorOutput.match(/\/org\/gnome\/SessionManager\/Inhibitor\d+/g);

    if (!objectPaths || objectPaths.length === 0) {
      console.log("No active inhibitors found.");
      return;
    }

    // Loop through each inhibitor and get details
    for (const path of objectPaths) {
      console.log(`Inhibitor: ${path}`);
      
      try {
        // Get App ID
        const appIdOutput = execSync(
          `gdbus call --session --dest org.gnome.SessionManager --object-path ${path} --method org.gnome.SessionManager.Inhibitor.GetAppId`
        ).toString().trim();
        
        // Get reason
        const reasonOutput = execSync(
          `gdbus call --session --dest org.gnome.SessionManager --object-path ${path} --method org.gnome.SessionManager.Inhibitor.GetReason`
        ).toString().trim();
        
        // Get flags
        const flagsOutput = execSync(
          `gdbus call --session --dest org.gnome.SessionManager --object-path ${path} --method org.gnome.SessionManager.Inhibitor.GetFlags`
        ).toString().trim();
        
        // Process outputs - clean up parentheses, quotes, etc.
        const appId = appIdOutput.replace(/[()'"]/g, '').replace(/,/g, '');
        const reason = reasonOutput.replace(/[()'"]/g, '').replace(/,/g, '');
        const flags = parseInt(flagsOutput.replace(/[()'"]/g, '').replace(/,/g, '').replace('uint32 ', ''));
        
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
        
        if (relevantLines.length > 0) {
          console.log(relevantLines.join('\n'));
        } else {
          console.log("No matching inhibitor found in systemd/logind");
        }
        
      } catch (error) {
        console.log(`  Error querying inhibitor: ${error.message}`);
      }
      
      console.log("----------------------------");
    }
    
    console.log("\n✅ How to clear inhibitors:");
    console.log("1. Close the app listed in App ID (if running)");
    console.log("2. If it's a GNOME Shell extension, disable it");
    console.log(`3. Force suspend ignoring inhibitors: systemctl suspend -i`);
    
  } catch (error) {
    if (error.message.includes('No such method')) {
      // Fall back to systemd/logind if GNOME methods aren't available
      console.log("GNOME SessionManager methods not available. Falling back to systemd/logind view:");
      try {
        const logindOutput = execSync('systemd-inhibit --list').toString();
        console.log(logindOutput);
      } catch (fallbackError) {
        console.error("Failed to get inhibitor info from systemd/logind:", fallbackError.message);
      }
    } else {
      console.error("Error:", error.message);
    }
  }
}

main().catch(console.error);
