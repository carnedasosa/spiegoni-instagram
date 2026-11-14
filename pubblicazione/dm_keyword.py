#!/usr/bin/env python3
"""DM automatico a chi commenta la keyword sotto un reel di Spiegoni (al posto di ManyChat).

A ogni giro (GitHub Actions, ogni 5 minuti):
  1. per ogni keyword attiva in keyword.json legge i commenti del suo reel (media_id da pubblicati.json);
  2. se un commento contiene la keyword come parola intera (maiuscole, minuscole e accenti non contano),
     non è dell'account stesso, ha meno di 7 giorni e non è già stato servito, manda la risposta privata
     in DM con il testo e il link del regalo, poi risponde sotto il commento alternando tre frasi;
  3. segna il commento in dm_serviti.json, così nessuno riceve il DM due volte.

Regole di Instagram: una sola risposta privata per commento, entro 7 giorni dal commento.
Richiede l'app Meta in modalità Live e il permesso instagram_business_manage_comments.

Il repo è pubblico e i log li vede chiunque: lo script stampa solo conteggi e codici d'errore, e in
dm_serviti.json salva un'impronta (sha256) dell'id del commento, mai testi, nomi o id delle persone.
Le impronte si cancellano dopo 30 giorni (lo promette la privacy policy in docs/privacy.html).

Uso:
  python3 dm_keyword.py            giro normale
  python3 dm_keyword.py --prova    conta cosa farebbe, senza mandare niente e senza scrivere file
  python3 dm_keyword.py --prova --tutte   come sopra, anche per le keyword spente o senza link
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://graph.instagram.com/v27.0"
QUI = Path(__file__).resolve().parent
FINESTRA = timedelta(days=7) - timedelta(minutes=15)   # margine sul limite dei 7 giorni
CONSERVA = timedelta(days=30)
TENTATIVI = 3            # dopo 3 errori sullo stesso commento si lascia stare
MASSIMO_PER_GIRO = 60    # Instagram ne permette di più (circa 750 l'ora): questo è un freno di sicurezza


class ErroreApi(Exception):
    def __init__(self, stato, codice, sotto):
        super().__init__(f"HTTP {stato}, codice {codice}, sottocodice {sotto}")
        self.codice, self.sotto = codice, sotto


def chiama(metodo, percorso, campi=None, corpo=None):
    url = f"{API}/{percorso}"
    if campi:
        url += "?" + urllib.parse.urlencode(campi)
    dati = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dati, method=metodo)
    req.add_header("Authorization", f"Bearer {os.environ['IG_ACCESS_TOKEN']}")  # mai nell'URL
    if dati is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode(errors="replace")).get("error", {})
        except Exception:
            err = {}
        # Solo i codici: alcuni messaggi di Meta contengono il nome della persona.
        raise ErroreApi(e.code, err.get("code"), err.get("error_subcode")) from None
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise ErroreApi(None, f"rete {type(e).__name__}", None) from None


def normalizza(testo):
    """Maiuscolo e senza accenti: CAFFÈ, caffe e Caffé diventano CAFFE."""
    t = unicodedata.normalize("NFKD", testo or "")
    return "".join(c for c in t if not unicodedata.combining(c)).upper()


def contiene(testo, keyword):
    return re.search(rf"(?<![A-Z0-9]){re.escape(normalizza(keyword))}(?![A-Z0-9])", normalizza(testo)) is not None


def impronta(comment_id):
    return hashlib.sha256(str(comment_id).encode()).hexdigest()[:24]


def quando(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")


def commenti(media_id):
    campi = {"fields": "id,text,timestamp,from", "limit": 50}
    letti, pagina = [], chiama("GET", f"{media_id}/comments", campi)
    while True:
        letti += pagina.get("data", [])
        dopo = pagina.get("paging", {}).get("cursors", {}).get("after")
        if not dopo or not pagina.get("paging", {}).get("next"):
            return letti
        pagina = chiama("GET", f"{media_id}/comments", {**campi, "after": dopo})


def leggi_json(nome, vuoto):
    f = QUI / nome
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else vuoto


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--prova", action="store_true", help="non manda niente e non scrive file")
    a.add_argument("--tutte", action="store_true", help="con --prova: guarda anche le keyword spente o senza link")
    arg = a.parse_args()
    if not os.environ.get("IG_ACCESS_TOKEN") or not os.environ.get("IG_USER_ID"):
        sys.exit("Mancano IG_ACCESS_TOKEN o IG_USER_ID.")
    user_id = str(os.environ["IG_USER_ID"])
    adesso = datetime.now(timezone.utc)

    cfg = leggi_json("keyword.json", {})
    pubblicati = leggi_json("pubblicati.json", {})
    serviti = leggi_json("dm_serviti.json", {})
    frasi = cfg.get("risposte_pubbliche") or []

    # Via le impronte più vecchie di 30 giorni.
    serviti = {k: v for k, v in serviti.items() if adesso - quando(v["il"]) < CONSERVA}

    if arg.tutte and not arg.prova:
        sys.exit("--tutte si usa solo con --prova.")
    attive = [v for v in cfg.get("keyword", []) if v.get("attivo") or arg.tutte]
    conti = {"mandati": 0, "risposte": 0, "errori": 0, "abbandonati": 0}
    print(f"Keyword attive: {len(attive)}" + (" (prova: non mando niente)" if arg.prova else ""))
    for v in attive:
        media_id = v.get("media_id") or (pubblicati.get(v["post"]) or {}).get("media_id")
        if not media_id:
            print(f"- {v['keyword']}: reel non ancora pubblicato via API, salto")
            continue
        if not arg.tutte and (not v.get("link") or "[PDF]" not in v.get("testo", "")):
            print(f"- {v['keyword']}: manca il link o [PDF] nel testo, salto")
            continue
        try:
            cc = commenti(media_id)
        except ErroreApi as e:
            if e.codice == 190:
                sys.exit(f"Token non valido ({e}): va rigenerato.")
            print(f"- {v['keyword']}: commenti non letti ({e})")
            continue
        nuovi = [c for c in cc
                 if contiene(c.get("text"), v["keyword"])
                 and str((c.get("from") or {}).get("id")) != user_id
                 and adesso - quando(c["timestamp"]) < FINESTRA
                 and serviti.get(impronta(c["id"]), {}).get("stato") not in ("ok", "rifiutato")]
        print(f"- {v['keyword']}: {len(cc)} commenti, {len(nuovi)} da servire")
        testo = v["testo"].replace("[PDF]", v["link"])
        for c in nuovi:
            if arg.prova or conti["mandati"] + conti["errori"] >= MASSIMO_PER_GIRO:
                continue
            k = impronta(c["id"])
            voce = serviti.get(k, {"tentativi": 0})
            try:
                chiama("POST", f"{user_id}/messages",
                       corpo={"recipient": {"comment_id": c["id"]}, "message": {"text": testo}})
            except ErroreApi as e:
                if e.codice == 190:
                    sys.exit(f"Token non valido ({e}): va rigenerato.")
                voce["tentativi"] = voce.get("tentativi", 0) + 1
                voce["stato"] = "rifiutato" if voce["tentativi"] >= TENTATIVI else "errore"
                voce["il"], voce["codice"] = adesso.strftime("%Y-%m-%dT%H:%M:%S%z"), f"{e.codice}/{e.sotto}"
                serviti[k] = voce
                conti["errori"] += 1
                conti["abbandonati"] += voce["stato"] == "rifiutato"
                print(f"  DM non mandato ({e}), tentativo {voce['tentativi']} di {TENTATIVI}")
                continue
            serviti[k] = {"stato": "ok", "il": adesso.strftime("%Y-%m-%dT%H:%M:%S%z"), "keyword": v["keyword"]}
            conti["mandati"] += 1
            if frasi:
                try:
                    chiama("POST", f"{c['id']}/replies", corpo={"message": frasi[int(k, 16) % len(frasi)]})
                    conti["risposte"] += 1
                except ErroreApi as e:
                    print(f"  risposta pubblica non fatta ({e})")
    print(f"Fatto: {conti['mandati']} DM, {conti['risposte']} risposte sotto i commenti, "
          f"{conti['errori']} errori ({conti['abbandonati']} lasciati stare).")
    if not arg.prova:
        (QUI / "dm_serviti.json").write_text(json.dumps(serviti, indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
