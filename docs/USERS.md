# Users, roles and server access

Administrators manage accounts, roles, active status, passwords and server assignments under **Benutzer** (Users). New passwords require at least 14 characters. Every user can click their **profile name at the bottom of the sidebar** to open **Mein Konto** (My account) and change their own password.

| Role | Permissions |
|---|---|
| Administrator | Manage all servers and users. |
| Manager (Verwalter) | Create servers; configure, install, operate, back up, archive and delete all servers, including newly created servers. |
| Operator | View assigned servers (or all servers when enabled), start, stop and restart them, and send console commands. |
| Viewer (Betrachter) | View the status, console and mod list of assigned servers. |

Administrators and managers have access to all current and future servers. Administrators can enable **Allow access to all servers** for an operator; otherwise operators and viewers see only assigned servers. This option expands server access without granting management or user administration permissions. It is disabled by default for existing and new operators, and is cleared when changing to another role. General host resource information remains visible to signed-in users. Files, backups and settings require administrator or manager permissions.

The API checks permissions on every request. Password, role and assignment changes, deactivation and account deletion invalidate existing sessions. The last active administrator cannot be removed. Administrators cannot deactivate, demote or delete their own account. Deleting a user does not delete any Minecraft servers.

Updates automatically migrate the existing administrator password. The database then manages accounts; changing the original installation hash afterward does not reset the administrator password. Include the database in regular backups.

## Refresh the user list

The user list loads when opened and after you save or delete an account. It does not refresh on a timer and has no separate refresh button. Reopen the user page or reload the browser and return to it to see changes made elsewhere. Unchanged results keep the current table in place. The global overview polling is also paused on the Users and My account pages, including sidebar and connection-label updates. Delayed background responses from another page are ignored. Live server and console views continue polling when you return to them.

## Permanently delete a server

Open **Einstellungen → Server löschen** (Settings → Delete server) and enter the exact server name. The server must be stopped and no installation or backup may be running. Deletion removes the management record, all server files including worlds and mods, and that server's backups stored in MineDock. Download any backups you want to retain and keep them outside MineDock beforehand. Archived servers can also be deleted.

Archiving retains files. Permanent deletion cannot be undone. If a filesystem operation fails, the management record remains so deletion can be retried; files already removed cannot be restored by that retry.

## Trust model

Roles control access to the panel. Minecraft processes run under a shared service user. Uploaded mods and JARs can execute code with that user's permissions. Give administrator and manager access only to trusted people; these roles do not provide process isolation for unrelated hosting customers. Operator console commands may also have broad effects depending on installed mods.
