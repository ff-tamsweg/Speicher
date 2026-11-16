# Speicher

Eigene Web-App zur Überwachung und Steuerung von Marstek-Venus-Speichern (getestet für den Aufbau mit drei Venus E 3.0 an L1, L2 und L3 und einem CT002).
Die App kann auf zwei Arten laufen:

- **Mit Marstek-Konto (nur iPhone, kein Gerät zuhause nötig):** Die Seite auf GitHub Pages öffnen, mit dem Marstek-Konto anmelden. Die Werte kommen von den Marstek-Servern, wie bei der Marstek-App. Nur Anzeige, Aktualisierung alle paar Minuten. Der Zugang ist nicht offiziell dokumentiert und kann sich durch Marstek ändern.
- **Im Heimnetz mit eigenem Server:** `speicher_app.py` auf einem Rechner zuhause starten. Dann direkte Abfrage über die lokale Schnittstelle (Marstek Open API, UDP), ohne Cloud, inklusive CT-Werten und Wechsel der Betriebsart.

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

## Einrichtung mit Marstek-Konto

1. Unter Settings > Pages dieses Repositorys GitHub Pages für den Branch `main` einschalten.
2. Die Seite in Safari öffnen, mit E-Mail und Passwort des Marstek-Kontos anmelden.
3. Teilen > Zum Home-Bildschirm.

Neue Speicher werden einmalig in der Marstek-App gekoppelt und ins WLAN eingebunden und erscheinen dann automatisch.

## Einrichtung im Heimnetz

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
