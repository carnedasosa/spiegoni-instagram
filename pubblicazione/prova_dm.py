#!/usr/bin/env python3
"""Prova del DM automatico ai commenti, con le API di Instagram e senza ManyChat (strada 1).

Serve a rispondere a una domanda sola: con l'app Meta in modalità sviluppo (Standard Access)
possiamo leggere i commenti di chiunque e mandare una risposta privata a chi NON ha un ruolo
nell'app? Se sì, il DM automatico si può fare da soli; se no, serve l'App Review.

Due azioni:
  leggi   sola lettura. Per ogni reel degli ultimi 7 giorni conta i commenti che Instagram
          dichiara, quelli che l'API restituisce e quelli con la keyword. Non scrive niente.
  invia   per i commenti con la keyword (di default PROVADM, che ManyChat non conosce) manda
          la risposta privata in DM, al massimo 3. Con --rispondi risponde anche sotto il commento.

Il repo è pubblico e i log di Actions li vede chiunque: lo script non stampa mai testi dei
commenti, username, id delle persone o il token. Solo conteggi, codici di errore e link dei reel.

Uso (sul runner di Actions, con IG_ACCESS_TOKEN e IG_USER_ID nei secret):
  python3 prova_dm.py leggi
  python3 prova_dm.py invia --keyword PROVADM [--rispondi]
"""
import argparse
import http.client
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://graph.instagram.com/v27.0"
GIORNI = 7            # le risposte private si possono mandare entro 7 giorni dal commento
MASSIMO_INVII = 3
LINK_REGALI = "https://drive.google.com/drive/folders/1-akDjQBYvWezbnhTxb91QD5rWC5omS4-"
TESTO_DM = (
    "Ciao! Questo è un test del DM automatico di Spiegoni: se lo leggi, funziona. "
    f"Qui ci sono i regali delle keyword: {LINK_REGALI}"
)
TESTO_RISPOSTA = "Fatto, ti ho scritto in DM. Se non lo vedi, guarda tra le richieste di messaggi."


class ErroreApi(Exception):
    def __init__(self, stato, codice, sotto, messaggio):
        super().__init__(f"HTTP {stato}, codice {codice}, sottocodice {sotto}: {messaggio}")
        self.codice, self.sotto = codice, sotto


def chiama(metodo, percorso, campi=None, corpo=None):
    token = os.environ["IG_ACCESS_TOKEN"]
    url = f"{API}/{percorso}"
    if campi:
        url += "?" + urllib.parse.urlencode(campi)
    dati = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dati, method=metodo)
    # Il token va nell'intestazione, non nell'URL: così non finisce in nessun messaggio d'errore.
    req.add_header("Authorization", f"Bearer {token}")
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
        # Solo i codici: alcuni messaggi di Meta contengono il nome della persona, e i log sono pubblici.
        raise ErroreApi(e.code, err.get("code"), err.get("error_subcode"), err.get("type", "errore")) from None
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise ErroreApi(None, None, None, f"rete: {type(e).__name__}") from None


def reel_recenti(user_id):
    limite = datetime.now(timezone.utc) - timedelta(days=GIORNI)
    dati = chiama("GET", f"{user_id}/media",
                  {"fields": "id,permalink,timestamp,comments_count", "limit": 25})
    out = []
    for m in dati.get("data", []):
        quando = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        if quando >= limite:
            out.append(m)
    return out


def commenti(media_id):
    """Tutti i commenti di primo livello di un reel, seguendo il cursore (mai l'URL next, che ha il token)."""
    campi = {"fields": "id,text,timestamp,username", "limit": 50}
    letti, pagina = [], chiama("GET", f"{media_id}/comments", campi)
    while True:
        letti += pagina.get("data", [])
        dopo = pagina.get("paging", {}).get("cursors", {}).get("after")
        if not dopo or not pagina.get("paging", {}).get("next"):
            return letti
        pagina = chiama("GET", f"{media_id}/comments", {**campi, "after": dopo})


def ha_keyword(testo, keyword):
    return keyword.lower() in (testo or "").lower()


def leggi(user_id, keyword):
    reel = reel_recenti(user_id)
    print(f"Reel degli ultimi {GIORNI} giorni: {len(reel)}")
    tot_dichiarati = tot_letti = 0
    for m in reel:
        try:
            cc = commenti(m["id"])
        except ErroreApi as e:
            print(f"- {m.get('permalink')}: lettura commenti NON riuscita ({e})")
            if e.codice in (10, 200, 3, 190):
                print("  -> al token manca instagram_business_manage_comments (o il token non vale più)")
            continue
        con_nome = sum(1 for c in cc if c.get("username"))
        trovati = sum(1 for c in cc if ha_keyword(c.get("text"), keyword))
        tot_dichiarati += m.get("comments_count") or 0
        tot_letti += len(cc)
        print(f"- {m.get('permalink')} ({m['timestamp'][:10]}): Instagram dice {m.get('comments_count')} "
              f"commenti, l'API ne restituisce {len(cc)} di primo livello "
              f"({con_nome} con username), con {keyword}: {trovati}")
    print(f"Totale: dichiarati {tot_dichiarati}, letti {tot_letti} (le risposte ai commenti non sono contate tra i letti).")


def diagnosi(user_id):
    """Sul reel con più commenti prova quattro modi di chiedere i commenti: conta solo quanti ne tornano."""
    reel = max(reel_recenti(user_id), key=lambda m: m.get("comments_count") or 0)
    print(f"Reel: {reel.get('permalink')}, Instagram dice {reel.get('comments_count')} commenti")
    token = os.environ["IG_ACCESS_TOKEN"]
    prove = {
        "comments, solo id, token nell'intestazione": lambda: chiama("GET", f"{reel['id']}/comments", {"fields": "id"}),
        "campo comments del reel": lambda: chiama("GET", reel["id"], {"fields": "comments{id}"}).get("comments", {}),
    }
    for nome, f in prove.items():
        try:
            print(f"- {nome}: {len(f().get('data', []))}")
        except ErroreApi as e:
            print(f"- {nome}: errore ({e})")
    for versione in ("v27.0", "v23.0"):
        url = (f"https://graph.instagram.com/{versione}/{reel['id']}/comments?"
               + urllib.parse.urlencode({"fields": "id", "access_token": token}))
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                print(f"- token nell'URL, {versione}: {len(json.load(r).get('data', []))}")
        except urllib.error.HTTPError as e:
            print(f"- token nell'URL, {versione}: errore HTTP {e.code}")


def invia(user_id, keyword, rispondi):
    # I commenti dell'account stesso (le prove fatte da @glispiegoni) non si contano: non si scrive a sé stessi.
    io = chiama("GET", "me", {"fields": "username"}).get("username", "").lower()
    candidati, miei = [], 0
    for m in reel_recenti(user_id):
        for c in commenti(m["id"]):
            if ha_keyword(c.get("text"), keyword):
                if io and (c.get("username") or "").lower() == io:
                    miei += 1
                else:
                    candidati.append((m, c))
    print(f"Commenti con {keyword} negli ultimi {GIORNI} giorni: {len(candidati)} di altri, {miei} dell'account "
          f"(saltati). Ne provo al massimo {MASSIMO_INVII}.")
    riusciti = 0
    for n, (m, c) in enumerate(candidati[:MASSIMO_INVII], 1):
        try:
            r = chiama("POST", f"{user_id}/messages",
                       corpo={"recipient": {"comment_id": c["id"]}, "message": {"text": TESTO_DM}})
            ok = bool(r.get("message_id"))
            riusciti += ok
            print(f"{n}. {m.get('permalink')}: risposta privata {'MANDATA' if ok else 'risposta strana: ' + ', '.join(r)}")
        except ErroreApi as e:
            print(f"{n}. {m.get('permalink')}: risposta privata NON mandata ({e})")
            continue
        if rispondi:
            try:
                chiama("POST", f"{c['id']}/replies", corpo={"message": TESTO_RISPOSTA})
                print("   risposta pubblica sotto il commento: fatta")
            except ErroreApi as e:
                print(f"   risposta pubblica NON fatta ({e})")
    print(f"Esito: {riusciti} DM mandati su {min(len(candidati), MASSIMO_INVII)}.")
    return riusciti


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("azione", choices=["leggi", "invia", "diagnosi"])
    a.add_argument("--keyword", default="PROVADM")
    a.add_argument("--rispondi", action="store_true", help="risponde anche sotto il commento")
    arg = a.parse_args()
    if not os.environ.get("IG_ACCESS_TOKEN") or not os.environ.get("IG_USER_ID"):
        sys.exit("Mancano IG_ACCESS_TOKEN o IG_USER_ID.")
    # Una keyword vuota o corta prenderebbe i commenti veri dei follower e scriverebbe a loro.
    if len(arg.keyword.strip()) < 5:
        sys.exit("Keyword troppo corta: usane una di almeno 5 lettere (es. PROVADM).")
    user_id = os.environ["IG_USER_ID"]
    try:
        if arg.azione == "diagnosi":
            diagnosi(user_id)
        elif arg.azione == "leggi":
            leggi(user_id, arg.keyword)
        elif invia(user_id, arg.keyword, arg.rispondi) == 0:
            sys.exit(1)
    except ErroreApi as e:
        sys.exit(f"Errore di Instagram: {e}")


if __name__ == "__main__":
    main()
