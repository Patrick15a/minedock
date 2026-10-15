# Benutzer, Rollen und Serverzugriff

Administratoren verwalten unter **Benutzer** Konten, Rollen, Aktivierung, Passwörter und Serverzuweisungen. Neue Passwörter benötigen mindestens 14 Zeichen. Unter **Mein Konto** kann jeder sein eigenes Passwort ändern.

| Rolle | Rechte |
|---|---|
| Administrator | Alle Server und Benutzer verwalten. |
| Verwalter | Server anlegen; zugewiesene Server konfigurieren, installieren, bedienen, sichern, archivieren und löschen. |
| Operator | Zugewiesene Server ansehen, starten, stoppen, neu starten und Konsolenbefehle senden. |
| Betrachter | Status, Konsole und Mod-Liste zugewiesener Server ansehen. |

Nicht-Administratoren sehen ausschließlich zugewiesene Server. Von einem Verwalter angelegte Server werden ihm automatisch zugewiesen. Ohne Zuweisung sieht ein Benutzer keine vorhandenen Server. Allgemeine Host-Ressourcen bleiben für angemeldete Benutzer sichtbar. Dateien, Backups und Einstellungen erfordern Administrator- oder Verwalterrechte.

Die API prüft die Rechte bei jeder Anfrage. Passwort-, Rollen- und Zuweisungsänderungen, Deaktivierung und Löschen eines Kontos machen bestehende Sitzungen ungültig. Der letzte aktive Administrator kann nicht entfernt werden. Administratoren können ihr eigenes Konto nicht deaktivieren, herabstufen oder löschen. Das Löschen eines Benutzers löscht keine Minecraft-Server.

Beim Update wird das vorhandene Admin-Passwort automatisch übernommen. Danach verwaltet die Datenbank die Konten; eine spätere Änderung des ursprünglichen Installations-Hashes setzt das Admin-Passwort nicht zurück. Die Datenbank gehört deshalb in die regelmäßige Sicherung.

## Server dauerhaft löschen

Unter **Einstellungen → Server löschen** den exakten Servernamen eingeben. Der Server muss gestoppt sein; es darf keine Installation oder Sicherung laufen. Die Aktion entfernt den Verwaltungsdatensatz, alle Serverdateien einschließlich Welten und Mods sowie die in MineDock gespeicherten Backups dieses Servers. Zuvor benötigte Backups herunterladen und außerhalb von MineDock aufbewahren. Archivierte Server lassen sich ebenfalls löschen.

Archivieren behält die Dateien. Dauerhaftes Löschen kann nicht rückgängig gemacht werden. Bei einem Dateisystemfehler bleibt der Verwaltungsdatensatz für einen erneuten Löschversuch erhalten; bereits gelöschte Dateien können dabei nicht wiederhergestellt werden.

## Vertrauensmodell

Die Rollen regeln den Zugriff auf das Panel. Minecraft-Prozesse laufen unter einem gemeinsamen Dienstbenutzer. Hochgeladene Mods und JARs können Code mit dessen Rechten ausführen. Administrator- und Verwalterrechte nur an vertrauenswürdige Personen vergeben; dies ist keine Prozessisolierung für fremde Hosting-Kunden. Auch Konsolenbefehle eines Operators können je nach installiertem Mod weitreichende Wirkung haben.
