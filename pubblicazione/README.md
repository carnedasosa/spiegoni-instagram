# Spiegoni · Pubblicazione automatica dei reel

Stesso metodo della pagina Wine Life, per i reel di @glispiegoni. I video si fanno nel repository privato
IG-3-trucchi: lì `./reel ig carica` copia qui i reel pronti e riscrive il calendario.

Cosa c'è qui:

- `video/`: i reel in MP4, una copia per Instagram del master: stesso video, audio AAC a 128 kbps.
- `jpg/`: le copertine in JPEG.
- `calendario.json`: data, ora, video, copertina e caption di ogni reel. Lo scrive `./reel ig carica`.
- `caption.md`: lo stesso calendario in forma leggibile, con le caption.
- `publish.py`: pubblica via API (`graph.instagram.com` v23.0), solo libreria standard di Python.
  Accetta post singoli e caroselli come Wine Life (`immagini`) e i reel (`video` + `copertina`).
- `../.github/workflows/pubblica.yml`: ai minuti 7 e 37 di ogni ora lancia `publish.py --due`.
- `pubblicati.json`: lo crea lo script e lo committa il bot, così niente esce due volte.
- `imposta_token.py`: salva `IG_ACCESS_TOKEN` e `IG_USER_ID` nei Secrets del repo senza mostrarli.

Il repository è pubblico perché Instagram scarica video e copertine da `raw.githubusercontent.com`.
I reel sono quindi visibili qui prima di uscire.

## Prove

```
python pubblicazione/publish.py --dry-run --due              # cosa uscirebbe adesso
python pubblicazione/publish.py --dry-run --post 03_coca_vs_pepsi
gh workflow run pubblica.yml -R carnedasosa/spiegoni-instagram                                  # "Niente da pubblicare adesso"
gh workflow run pubblica.yml -R carnedasosa/spiegoni-instagram -f post=ID -f verifica=true      # prepara, NON pubblica
```

Su Windows, prima: `$env:PYTHONIOENCODING="utf-8"`.

## Token

Dura 60 giorni. Si rigenera dalla dashboard Meta, poi `python pubblicazione/imposta_token.py`.
