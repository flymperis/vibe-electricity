# Vibe Electricity με Podman Quadlet

Το Vibe Electricity τρέχει ως systemd service του χρήστη (rootless): ξεκινά στο boot και κάνει restart αν πέσει.
Χρειάζεται **Podman 5.2+**, λόγω του αρχείου `.build`.

| Αρχείο | Ρόλος |
|---|---|
| `vibe-electricity.build` | Χτίζει το image `localhost/vibe-electricity` από το clone του repo |
| `vibe-electricity.volume` | Το volume `vibe-electricity-data` με τη βάση SQLite |
| `vibe-electricity.container` | Το service: port 8002, `.env`, healthcheck, restart |

## Εγκατάσταση

```bash
# 1. Κώδικας και ρυθμίσεις. Το .build περιμένει το repo στο ~/vibe-electricity
git clone https://github.com/flymperis/vibe-electricity.git ~/vibe-electricity
cp ~/vibe-electricity/.env.example ~/vibe-electricity/.env
chmod 600 ~/vibe-electricity/.env        # έχει το token του Paperless
#    PAPERLESS_URL / PAPERLESS_TOKEN / OLLAMA_URL

# 2. Quadlet units. Αν το Paperless και το Ollama είναι containers σε δικό τους network, βάλε το
#    Network= στο vibe-electricity.container ώστε να τα βρίσκει με το όνομά τους.
mkdir -p ~/.config/containers/systemd
cp ~/vibe-electricity/deploy/quadlet/vibe-electricity.* ~/.config/containers/systemd/
systemctl --user daemon-reload

# 3. Εκκίνηση (η πρώτη φορά χτίζει το image)
systemctl --user start vibe-electricity.service

# 4. Να τρέχει και χωρίς να είσαι συνδεδεμένος (μία φορά)
loginctl enable-linger "$USER"
```

## Καθημερινή χρήση

```bash
systemctl --user status vibe-electricity.service
journalctl --user -u vibe-electricity.service -f
~/vibe-electricity/deploy/update.sh       # update: backup βάσης, git pull, rebuild, restart, healthcheck
```

Το `update.sh` αλλάζει μόνο τον κώδικα. Δεν αγγίζει τη βάση (μόνο κρατά backup στο `/data/backups`), το `.env` ή τα
units στο `~/.config/containers/systemd`. Οι αλλαγές στο σχήμα της βάσης γίνονται αυτόματα στην εκκίνηση και μόνο
προσθέτουν στήλες.

## Η βάση σε δικό σου φάκελο (π.χ. RAID)

Από προεπιλογή η βάση είναι στο storage του Podman. Μεταφορά σε δικό σου φάκελο:

```bash
DIR=/srv/vibe-electricity          # φάκελος μόνο για το Vibe Electricity (παίρνει SELinux label)
systemctl --user stop vibe-electricity.service
podman volume export vibe-electricity-data -o ~/vibe-electricity-data-backup.tar
mkdir -p "$DIR"
podman unshare cp -a "$(podman volume inspect vibe-electricity-data --format '{{.Mountpoint}}')/." "$DIR/"
podman unshare chown -R 1000:1000 "$DIR"
# ξεσχολίασε Device= (= $DIR), Type= και Options= στο ~/.config/containers/systemd/vibe-electricity.volume
podman rm -f vibe-electricity
podman volume rm vibe-electricity-data
systemctl --user daemon-reload
systemctl --user restart vibe-electricity-volume.service   # αλλιώς το παλιό volume service θεωρείται ήδη ενεργό
systemctl --user start vibe-electricity.service
```

Έλεγχος: το `podman volume inspect vibe-electricity-data --format '{{.Options}}'` πρέπει να δείχνει `device:<φάκελος>`.
Αν βγάζει `map[]`, το container έφτιαξε νέο, άδειο volume. Σε αυτή την περίπτωση επανάλαβε τα βήματα από το `podman rm -f`.
