# Alabama Markdown MCP server

Ez a repository minden `.md` fájlját egy **read-only Model Context Protocol (MCP)** szerveren keresztül teszi kereshetővé és olvashatóvá. A szerver a Valyu DeepResearch egyedi MCP-forrásaként használható.

> **Adatvédelmi figyelmeztetés:** a repository jelenleg jogi és személyes adatokat tartalmaz. A remote MCP-szerver **nem igényel hitelesítést**, ezért az interneten keresztül hozzáférő bárki a teljes Markdown-tartalmat el tudja olvasni. Csak megbízható kliensekhez csatlakoztasd, és ne tedd közzé a szerver URL-jét.

## Mit biztosít a szerver?

- `search(query)` – a repository összes Markdown-fájljában keres, és citable `id`/`title`/`url` találatokat ad vissza.
- `fetch(id)` – visszaadja a keresési találathoz tartozó teljes Markdown-fájlt.
- `list_documents()` – felsorolja a repository összes elérhető Markdown-fájlját és azok metaadatait (a jelenlegi checkoutban 148-at, az `README.md`-vel együtt).
- `search_documents(query, max_results)` – interaktív használathoz pontszámot és rövid snippetet is ad.
- `get_document(id, start_line, max_lines)` – nagy dokumentumok részleteinek lekérése.

A `search` és `fetch` szándékosan a Valyu/DeepResearch és más deep-research kliensek által elvárt, read-only kompatibilitási felületet követi. A szerver nem írja és nem módosítja a repository fájljait.

## Lokális indítás és teszt

Python 3.11+ szükséges.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt

# Helyi MCP Inspector / MCP kliens számára, stdio transporttal:
MCP_TRANSPORT=stdio python server.py

# HTTP tesztként:
python server.py
```

HTTP esetén az endpointok:

- Streamable HTTP: `http://localhost:8000/mcp`
- Legacy SSE: `http://localhost:8000/sse`
- Health check: `http://localhost:8000/health`
- Böngészőből olvasható citation endpoint: `http://localhost:8000/documents/<encoded-id>`

A szerver semmilyen hitelesítést nem vár: az MCP-kliens a token nélkül, közvetlenül csatlakozhat az endpointra (pl. `https://<host>/mcp`). A FastMCP OAuth-hitelesítése nincs bekapcsolva.

### Gyors health check

```bash
curl http://localhost:8000/health
```

## Deploy Renderre – legegyszerűbb remote megoldás

A repository tartalmaz `Dockerfile`-t és `render.yaml` Blueprintet.

1. Pushold ezt a branchet GitHubra, vagy a módosítások merge-elése után válaszd ki a repositoryt Renderben.
2. Renderben: **New → Blueprint** vagy **New Web Service**, repository: `cupcakke/alabama`.
3. Docker runtime esetén a `Dockerfile` automatikusan indul. A szerver hitelesítés nélkül, nyilvánosan érhető el — az endpoint URL-jét ne tedd közzé.
4. A deploy után ellenőrizd:

   ```bash
   curl https://<render-service>.onrender.com/health
   ```

   A válaszban a `documents` mezőnek a repository aktuális Markdown-fájljainak számát kell mutatnia (a jelenlegi checkoutban 148-at, az `README.md`-vel együtt).

5. Másold ki az MCP endpointot:

   ```text
   https://<render-service>.onrender.com/mcp
   ```

6. Ha a Render service URL-jét szeretnéd citation URL-ként használni, add hozzá a service environment változóihoz:

   ```text
   PUBLIC_BASE_URL=https://<render-service>.onrender.com
   ```

   Enélkül a találatok a `CITATION_BASE_URL` alapértelmezett GitHub blob URL-jére hivatkoznak.

Más Docker-kompatibilis host is használható. A konténer `0.0.0.0`-n figyel, és a host által megadott `PORT` értéket használja.

## Csatlakoztatás Valyu DeepResearch-höz

A Valyu DeepResearch task `mcp_servers` mezőjében add meg a saját deployed szerveredet. A Valyu API jelenlegi konfigurációs formája:

```json
{
  "mcp_servers": [
    {
      "url": "https://<render-service>.onrender.com/mcp",
      "name": "Alabama case documents",
      "allowed_tools": [
        "search",
        "fetch"
      ]
    }
  ]
}
```

Példa teljes DeepResearch kérésre:

```bash
curl -X POST https://api.valyu.ai/v1/deepresearch/tasks \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $VALYU_API_KEY" \
  -d @- <<'JSON'
{
  "query": "Vizsgáld meg a repository releváns iratait, keresd meg a kérdéshez kapcsolódó dátumokat és egymásnak ellentmondó állításokat, és minden állítást dokumentum- és oldalszintű hivatkozással támassz alá.",
  "mode": "standard",
  "mcp_servers": [
    {
      "url": "https://<render-service>.onrender.com/mcp",
      "name": "Alabama case documents",
      "allowed_tools": ["search", "fetch"]
    }
  ]
}
JSON
```

A Valyu felületén ugyanezeket az adatokat kell megadni az **MCP server / custom MCP** mezőknél: URL, név és a `search`, `fetch` engedélyezése. Hitelesítés nem szükséges, az `auth` mezőt ne töltsd ki.

Használható kutatási utasítás:

> Először mindig hívd meg az `alabama.search` eszközt a releváns iratok azonosítására, majd az eredmények `id` értékeivel hívd meg az `alabama.fetch` eszközt. Ne próbáld a dokumentumokat a fájlnevek alapján összefoglalni. Csak a lekért szöveg alapján állíts tényt, és a válaszban használd a visszaadott citation URL-eket.

## Deploy Modalra

A `modal_app.py` közvetlenül a repository teljes Markdown-korpusát csomagolja Modal image-be, és a meglévő read-only MCP ASGI alkalmazást teszi ki HTTPS-en. A Modal hivatalosan támogatja az ASGI appok és a stateless Streamable HTTP MCP szerverek futtatását.

### Egyszeri helyi beállítás

A Modal CLI telepítése és a workspace-authentication a saját gépeden történik:

```bash
python -m pip install -r requirements-modal.txt
modal setup
```

Ezután deploy:

```bash
modal deploy modal_app.py
```

A CLI kiír egy `https://...modal.run` URL-t. A Valyu MCP URL-je ennek a végére illesztett `/mcp`:

```text
https://<modal-endpoint>.modal.run/mcp
```

A Valyu DeepResearch konfigurációban hitelesítés nélkül add meg az endpointot:

```json
{
  "url": "https://<modal-endpoint>.modal.run/mcp",
  "name": "Alabama case documents",
  "allowed_tools": ["search", "fetch"]
}
```

A Modal endpoint scale-to-zero módban indulhat, ezért az első Valyu-kérés hidegindítással járhat. A fájlok a deploy időpontjában kerülnek az image-be; egy új repository-verzióhoz futtasd újra a `modal deploy modal_app.py` parancsot. A `modal deploy` parancshoz aktív Modal-fiók és a helyi Modal CLI-authentication szükséges.

## Környezeti változók

| Változó | Alapértelmezett | Leírás |
| --- | --- | --- |
| `MCP_ROOT` | `server.py` könyvtára | A beolvasandó repository-gyökér. Dockerben `/app`. |
| `PORT` | `8000` | HTTP port; a legtöbb PaaS felülírja. |
| `PUBLIC_BASE_URL` | üres | Ha megadod, a citation URL-ek ezt a hostot használják. |
| `CITATION_BASE_URL` | GitHub `main` blob URL | Fallback citation host. Állítsd a tényleges adatbranchre. |
| `MAX_SEARCH_RESULTS` | `10` | A kompatibilis `search` legfeljebb ennyi találatot ad. |
| `MAX_FETCH_CHARS` | `2,000,000` | Biztonsági válaszlimit; a jelenlegi legnagyobb fájl ennél kisebb. |

## Biztonsági megjegyzések

- A szerver **nem igényel hitelesítést**: aki eléri az URL-t, az minden Markdown-fájlt el tud olvasni. Nyilvános hoston az endpoint URL-jét ne tedd közzé.
- Csak `.md` fájlok olvashatók; a `.git`, virtualenv és symlinkek ki vannak zárva.
- A `fetch` és a helper eszközök nem engednek path traversal-t (`../`) és nem írnak lemezre.
- A dokumentumok tartalma prompt injectiont is tartalmazhat. A Valyu kutatási utasításában kezeld az iratokat adatként, ne végrehajtandó utasításként.
