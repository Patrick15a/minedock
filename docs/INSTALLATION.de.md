# MineDock

Privates Minecraft-Java-Panel für **Debian 13, ohne Docker**, mit Benutzerrollen und einem gemeinsamen Minecraft-RAM-Budget von 32 GiB. Eigenständige Python/FastAPI-Anwendung mit einer deutschen Browseroberfläche. Daten, Zugang und Serverprozesse liegen auf deinem Host; keine Sites-/Cloud-Abhängigkeit.

## Gestaltung

Deutschsprachige BexoGames-Oberflaeche mit dunklem Design und gruenen Akzenten. Die veroeffentlichte Fassung enthaelt keine Verknuepfung zu einem privaten Infrastruktur-Panel.

## Enthalten

- Server anlegen, starten, geordnet stoppen, neu starten und archivieren.
- Vanilla-Versionen installieren, eigene ausführbare Server-JARs hochladen.
- CurseForge-Dateilinks (konkrete `/files/ID`-Version) und CurseForge-ZIP-Exporte importieren.
- Fabric, Forge und NeoForge aus dem Manifest installieren; Mods und unterstützte Overrides übernehmen.
- Fehlende, nicht automatisiert herunterladbare Mods anzeigen und manuell hochladen, inklusive Prüfsummenprüfung, sofern CurseForge sie liefert.
- Mods hochladen, aktivieren, deaktivieren und entfernen.
- RAM, Java-Version, Port, Beschreibung, Spielmodus, Schwierigkeit, Spielerlimit und Whitelist einstellen.
- Konsole mit Befehlen und den letzten 1.200 Logzeilen; pollt alle 3,5 Sekunden.
- Konfigurationsdateien bis 1 MiB bearbeiten (gestoppter Server).
- Backups bei gestopptem Server erzeugen und herunterladen.
- Passwort-Hash, HttpOnly-Sitzung, CSRF-Schutz, Login-Drosselung, begrenzte Uploads und geprüfte Archivpfade.

## Installation auf Debian 13

Das Skript installiert Python, Java 21 und einen systemd-Dienst. Es richtet **keine Firewall und keine bestehende Webserver-Konfiguration automatisch um**. Es muss aus dem entpackten Projektverzeichnis gestartet werden:

```bash
sudo bash deploy/install.sh
```

Das Skript fragt nach einem eigenen Admin-Passwort und dem CurseForge-API-Schlüssel. Login: **admin**. Kein Standardpasswort. Für die CurseForge-Funktionen ist ein API-Schlüssel erforderlich. **Dieser Schlüssel darf niemals geteilt, an andere Personen weitergegeben oder veröffentlicht werden.** Die Eingabe kann bei der Installation übersprungen und später ergänzt werden.

Pfade:

| Zweck | Pfad |
|---|---|
| Anwendung | `/opt/minedock` |
| Konfiguration | `/etc/minedock/minedock.env` (root, 0600) |
| Datenbank | `/var/lib/minedock/panel.sqlite3` |
| Serverdaten | `/var/lib/minedock/servers/<ID>` |
| Backups | `/var/lib/minedock/backups` |

```bash
sudo systemctl status minedock
sudo journalctl -u minedock -n 100 --no-pager
```

## Proxmox: Minecraft-Container und Apache-Webserver-Container

MineDock läuft im Debian-13-Minecraft-Container. HTTPS wird im separaten Webserver-Container von Apache2 beendet; Apache leitet intern per HTTP an MineDock weiter.

Der Dienst lauscht standardmäßig auf **allen IPv4-Interfaces, Port 8080** (`MINEDOCK_BIND="0.0.0.0"`). Es wird keine Zugriffsbeschränkung auf die IP des Webservers gesetzt und keine Firewall verändert. Ein Worker ist erforderlich, da Prozessverwaltung und Sitzungen in diesem Prozess leben.

### Im Minecraft-Container

In `/etc/minedock/minedock.env` die tatsächliche Quell-IP des Apache-Containers eintragen:

```ini
MINEDOCK_BIND="0.0.0.0"
MINEDOCK_PORT="8080"
MINEDOCK_PROXY_IPS="APACHE_CONTAINER_IP"
MINEDOCK_SECURE_COOKIE="1"
```

`APACHE_CONTAINER_IP` ist ein Platzhalter und muss ersetzt werden. `MINEDOCK_PROXY_IPS` steuert nur, von welchen Absendern die Anwendung die weitergereichten HTTPS-/Client-IP-Informationen übernimmt. Andere Clients dürfen den Port weiterhin erreichen. Bei NAT ist die am Minecraft-Container sichtbare Proxy-Quell-IP einzutragen.

```bash
sudo systemctl restart minedock
```

Bei einer vorhandenen Installation zuerst die aktualisierte `deploy/minedock.service` nach `/etc/systemd/system/minedock.service` kopieren und `sudo systemctl daemon-reload` ausführen. Minecraft-Server vor dem Dienst-Neustart stoppen.

### Im Apache-Webserver-Container

Die Vorlage `deploy/apache2.conf` verwendet eine eigene Panel-Domain am URL-Hauptpfad. Ersetze `panel.example.com`, `MINECRAFT_CONTAINER_IP` und die Zertifikatspfade durch eure Werte. DNS und das Zertifikat gehören zum Webserver-Container. Eine bestehende Manager-Domain oder deren vHost nicht überschreiben.

```bash
sudo a2enmod proxy proxy_http headers ssl
sudo cp deploy/apache2.conf /etc/apache2/sites-available/minedock.conf
sudo a2ensite minedock.conf
sudo apache2ctl configtest
sudo systemctl reload apache2
```

Die kopierte Datei muss vor Aktivierung gültige Domain-, Backend- und Zertifikatswerte enthalten. Euren vorhandenen Zertifikats-/Erneuerungsablauf verwenden. `ProxyPreserveHost` erhält die Panel-Domain; `X-Forwarded-Proto` wird von Apache auf HTTPS gesetzt. Das Uploadlimit beträgt 513 MiB einschließlich Multipart-Daten. Die Konsole verwendet HTTP-Polling und benötigt kein WebSocket-Modul.

Browserzugriff erfolgt über die HTTPS-Panel-Domain. Minecraft-Spielverbindungen verwenden weiterhin die jeweiligen TCP-Spielports. Die mitgelieferte Konfiguration setzt keine IP-Zugriffsliste auf den Backend-Port.

### Optionaler Test über SSH-Tunnel

Für einen HTTP-Test ohne Domain `MINEDOCK_SECURE_COOKIE="0"` setzen und den Dienst neu starten. Mit der Standardkonfiguration bleibt Port 8080 auch über die Container-IP erreichbar. Falls für diesen Test ausdrücklich nur Loopback gewünscht ist, zusätzlich `MINEDOCK_BIND="127.0.0.1"` setzen. Auf dem PC:

```bash
ssh -L 8080:127.0.0.1:8080 BENUTZER@MINECRAFT-CONTAINER
```

Dann `http://localhost:8080` öffnen. Vor dem regulären Reverse-Proxy-Betrieb wieder `MINEDOCK_SECURE_COOKIE="1"` und die gewünschte Bind-Adresse setzen.

## Erster Server

1. Anmelden und **Server erstellen** wählen.
2. CurseForge-Dateilink, ZIP-Export, Vanilla oder eigene JAR auswählen.
3. RAM und Port vergeben; Java passend zur Minecraft-/Modpack-Version auswählen.
4. Minecraft-EULA selbst lesen und bei Zustimmung bestätigen. Vorher ist der Start gesperrt.
5. Installation in der Konsole beobachten. Fehlende Mods im Tab **Mods** herunterladen und hochladen.
6. Starten. Der Java-Prozess kann bereits laufen, während Minecraft noch lädt; erst die `Done`-Meldung bestätigt die Spielbereitschaft.

Ein CurseForge-Export enthält `manifest.json` im ZIP-Hauptverzeichnis. Klassische Server-Packs mit beliebigen Startskripten sind kein unterstütztes Importformat. Es werden nur Overrides in `mods`, `config`, `defaultconfigs`, `kubejs`, `scripts`, `resourcepacks` und `datapacks` übernommen. Mitgelieferte Welten und beliebige Root-Dateien werden nicht importiert. Client-only-Mods sind nicht zuverlässig automatisch erkennbar; bei Bedarf vor dem Start in der Mod-Liste deaktivieren.

Eine eigene Server-JAR muss direkt mit `java -jar … nogui` startfähig sein. Forge-/NeoForge-Installer bitte über ein CurseForge-Manifest installieren.

## Java und RAM

Java 21 wird mitinstalliert. Ältere Modpacks benötigen häufig Java 8 oder 17; neuere Versionen können weitere Java-Versionen benötigen. Installiere passende JREs aus einer vertrauenswürdigen Quelle und ergänze die absoluten Pfade in der Host-Konfiguration. Beispiel-Inhalt der systemd-EnvironmentFile:

```ini
MINEDOCK_JAVA='{"21":"/usr/lib/jvm/java-21-openjdk-amd64/bin/java","17":"/opt/java17/bin/java"}'
MINEDOCK_MEMORY_MB="32768"
```

Die Beispielpfade müssen auf deinem Host tatsächlich existieren. Nur die dort konfigurierten Java-Versionen werden zur Auswahl angeboten. Alle Minecraft-Server vor einer Dienst-Neukonfiguration stoppen.

Beim Start werden `-Xmx` plus 768 MiB pro laufendem Server gegen das gemeinsame Budget geprüft. Das ist eine Reservierungsrechnung, keine individuelle cgroup-Grenze. Der systemd-Dienst begrenzt das **gesamte Panel einschließlich Java-Kindprozessen** zusätzlich auf 32 GiB (`MemoryMax`); native Java-Nutzung und Mods können den Heap überschreiten. Bei Erreichen der Grenze kann der Kernel Prozesse beenden. Für den Host und andere Dienste muss ausreichend zusätzlicher RAM bleiben; hat der Rechner insgesamt nur 32 GiB, Budget und MemoryMax entsprechend reduzieren. Keine automatische Start-/Crash-Neustartschleife für Minecraft.

## Betrieb und Grenzen dieser ersten Version

- Benutzerrollen und Serverzuweisungen kontrollieren den Panel-Zugriff. Keine Trennung der Minecraft-Prozesse durch eigene Benutzer/Container. Administratoren und Verwalter müssen vertrauenswürdig sein. Hochgeladene Mods und JARs führen Code unter dem Dienstbenutzer aus und können dessen Daten lesen. Nur vertrauenswürdige Dateien verwenden.
- Der Dienst läuft ohne root und kann nur seinen Datenbereich schreiben. Java-Prozesse gehören zum Dienst. Beim regulären Panel-Stopp werden sie geordnet beendet; nach einem Panel-/Host-Neustart werden sie **manuell** gestartet. Minecraft schreibt zusätzlich eigene Logs im Serververzeichnis; Panel-Konsolenpuffer und Sitzungen gehen beim Neustart verloren.
- Modpack-Updates werden als **neuer Server** installiert. Kein Überschreiben bestehender Welten und kein automatisches In-place-Upgrade.
- Archive behalten ihre Dateien. Wiederherstellung eines archivierten Verwaltungsdatensatzes ist noch nicht in der Oberfläche vorhanden. Ein archivierter Server kann weiterhin gelesen und sein vorhandenes Backup heruntergeladen werden.
- ZIP-Limit 512 MiB komprimiert, 2 GiB entpackt, 20.000 Einträge. Jede heruntergeladene Datei maximal 512 MiB. Große Packs können diese Grenzen überschreiten.
- Backups enthalten Serverdateien, nicht die Panel-Datenbank und nicht den API-Schlüssel. Für eine vollständige Migration `/var/lib/minedock` und `/etc/minedock` bei gestopptem Dienst separat sichern.
- Eine Backup-Wiederherstellung über die Website ist noch nicht enthalten. Ein selbst erstelltes, vertrauenswürdiges Backup bei gestopptem Dienst zunächst in ein **neues temporäres Verzeichnis** entpacken, Inhalt prüfen und dann gezielt zurückkopieren. Bestehenden Serverordner vorher sichern; Eigentümer muss `minedock` bleiben.
- Panel-Installation und HTTPS-Anmeldung wurden auf Debian 13 im LXC erfolgreich geprueft. Echte Minecraft-Starts, externe Loader-Installationen und vollständige CurseForge-Imports sind noch nicht abgenommen.

## Entwicklung und Tests

Python 3.11+:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

Das Testsystem verwendet temporäre Daten und simulierte externe Downloads/Java-Prozesse. Es kontaktiert CurseForge nicht. Niemals echte Serverdaten als Testverzeichnis setzen.

## Benutzer und Rollen

Siehe [Benutzerverwaltung, Rollen und Löschen](USERS.de.md). Der bestehende Administrator wird beim ersten Start übernommen. Danach liegen Konten und Passwort-Hashes in der Datenbank; der Installations-Hash setzt ein dort geändertes Passwort nicht zurück.

## Upgrade

Alle von MineDock verwalteten Minecraft-Server stoppen und laufende Importe abwarten. Den Panel-Dienst für die Vorprüfung laufen lassen. Aus dem entpackten neuen Projektverzeichnis:

```bash
sudo /opt/minedock/.venv/bin/python deploy/update.py
```

Das Skript prüft die vorhandene Installation und unveränderte Abhängigkeiten, sichert Anwendung und Datenbank unter `/var/backups/minedock` und ersetzt den Anwendungscode. Bei einem fehlgeschlagenen Dienststart werden Code und Datenbank zurückgesetzt. Die bestehende Environment-Datei, systemd-Einstellungen, RAM-Grenzen, private Menüverknüpfungen und Minecraft-Dateien bleiben erhalten. Die Sicherung ist nur für root zugänglich. Danach im Browser neu laden und erneut anmelden.

## Technische Quellen

- [CurseForge REST API](https://docs.curseforge.com/rest-api/)
- [API-Key bei CurseForge-Dateidownloads](https://blog.curseforge.com/introducing-api-key-authentication-for-curseforge-file-downloads/)
- [Fabric-Serverinstallation](https://wiki.fabricmc.net/install)
- [NeoForge-Serverinstallation](https://docs.neoforged.net/user/docs/server/)

- [Apache Reverse Proxy](https://httpd.apache.org/docs/2.4/mod/mod_proxy.html)
- [Apache RequestHeader](https://httpd.apache.org/docs/2.4/mod/mod_headers.html)
