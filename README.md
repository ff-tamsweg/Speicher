# Speicher

Eigene Web-App zur Überwachung und Steuerung von Marstek-Venus-Speichern (getestet für den Aufbau mit drei Venus E 3.0 an L1, L2 und L3 und einem CT002).
Die App liest die Speicher direkt im Heimnetz über deren lokale Schnittstelle (Marstek Open API, UDP) aus. Eine Cloud wird nicht verwendet.

**Vorschau mit simulierten Werten:** über GitHub Pages dieses Repositorys (Link in der Seitenleiste). Die Vorschau zeigt keine echten Daten, weil eine Webseite aus dem Internet die Geräte im Heimnetz nicht erreichen kann.

## Funktionen

- Übersicht der Speicher als Module in den Phasenfarben, mit Ladestand, Lade- und Entladeleistung
- Anlage gesamt: gespeicherte Energie, Leistung, Netzwerte je Phase vom CT, heute geladen und entladen
- Hinweise, wenn ein Speicher nicht antwortet oder keine CT-Messwerte hat
- Verlauf von Ladestand und Leistung der letzten 24 Stunden
- Betriebsart je Speicher ändern: Eigenverbrauch, KI-Optimierung, feste Leistung für eine Dauer, täglicher Zeitplan
- Speicher im Heimnetz suchen, hinzufügen, einer Phase zuordnen
- Auf dem Handy als App auf den Home-Bildschirm legbar, helles und dunkles Erscheinungsbild

## Was die App nicht kann

- **Ersteinrichtung per Bluetooth und WLAN-Einbindung.** Marstek legt das Bluetooth-Protokoll nicht offen, und Safari auf dem iPhone unterstützt kein Web Bluetooth. Die Ersteinrichtung bleibt deshalb in der Marstek-App.
- Firmware-Updates.
- Werte des Mikrowechselrichters und des CT002 direkt abfragen. Die CT-Werte kommen über die Speicher.

## Einrichtung

### 1. In der Marstek-App, je Speicher einmalig
1. Speicher per Bluetooth koppeln und ins Heim-WLAN (2,4 GHz) einbinden.
2. Lokale Schnittstelle (Open API) einschalten, UDP-Port 30000.
3. Im Router eine feste IP-Adresse vergeben.

### 2. App starten
Benötigt Python 3.8 oder neuer auf einem Rechner, der im Heimnetz dauerhaft läuft (PC, Raspberry Pi, NAS mit Python). Zusätzliche Pakete sind nicht nötig.

```
git clone <Adresse dieses Repositorys>
cd <Ordner>
python speicher_app.py            # ohne Schutz
python speicher_app.py --pin 1234 # mit PIN-Abfrage im Browser
python speicher_app.py --demo     # Probelauf mit simulierten Speichern
```

Das Programm zeigt beim Start die Adresse an, zum Beispiel `http://192.168.1.20:8080`. Diese am Handy öffnen, dann **Teilen > Zum Home-Bildschirm**.

Unter **Geräte > Speicher hinzufügen** die Speicher suchen lassen oder die IP-Adresse eintragen und die Phase wählen.

### 3. Zugriff von unterwegs
Über eine VPN-Verbindung ins Heimnetz, zum Beispiel WireGuard am Router oder Tailscale. Die App nicht per Portfreigabe ins Internet stellen: Die Verbindung ist unverschlüsselt.

## Beim ersten Betrieb prüfen

- **Vorzeichen:** Die Marstek-Dokumentation legt nicht fest, ob positive Leistung Laden oder Entladen bedeutet. Zeigt die App beim Laden „Entlädt“, unter Einstellungen umschalten. Dasselbe gilt für Netzbezug und Einspeisung am CT.
- **Energiezähler:** Die Skalierung kann je nach Firmware abweichen. Mit der Marstek-App vergleichen.
- **Abfrage-Intervall:** Standard 60 Sekunden. Kürzere Abstände können laut Nutzerberichten die Verbindung zwischen Speicher und CT stören.

## Dateien

| Datei | Inhalt |
|---|---|
| `speicher_app.py` | Server: fragt die Speicher ab, speichert den Verlauf, liefert die Oberfläche aus |
| `index.html` | Oberfläche |
| `speicher_config.json` | wird beim Betrieb angelegt: eingetragene Geräte und Einstellungen |
| `speicher_verlauf.db` | wird beim Betrieb angelegt: Messwerte der letzten 30 Tage |

## Hinweis

Keine offizielle Software von Marstek. Benutzung auf eigene Verantwortung, insbesondere beim Ändern der Betriebsart.
