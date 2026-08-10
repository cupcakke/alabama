# Alabama Markdown MCP server

Ez a repository minden `.md` fájlját egy **read-only Model Context Protocol (MCP)** szerveren keresztül teszi kereshetővé és olvashatóvá. A szerver a Valyu DeepResearch egyedi MCP-forrásaként használható.

> **Adatvédelmi figyelmeztetés:** a repository jelenleg jogi és személyes adatokat tartalmaz. A remote MCP-szerverhez interneten keresztül hozzáférő kliens a teljes Markdown-tartalmat el tudja olvasni. Csak megbízható Valyu-fiókhoz csatlakoztasd, használj hosszú véletlen tokent, és ne tedd közzé a tokent.

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
MCP_AUTH_TOKEN=dev-token python server.py
```

HTTP esetén az endpointok:

- Streamable HTTP: `http://localhost:8000/mcp`
- Legacy SSE: `http://localhost:8000/sse`
- Health check: `http://localhost:8000/health`
- Böngészőből olvasható citation endpoint: `http://localhost:8000/documents/<encoded-id>`

A `MCP_AUTH_TOKEN` nincs kötelezővé téve lokális fejlesztésben. Internetre kitett szervernél **kötelező** beállítani. A kliens ezt küldje:

```http
Authorization: Bearer <MCP_AUTH_TOKEN>
```

### Gyors health check

```bash
curl http://localhost:8000/health
curl -H "Authorization: Bearer dev-token" http://localhost:8000/health
```

## Deploy Renderre – legegyszerűbb remote megoldás

A repository tartalmaz `Dockerfile`-t és `render.yaml` Blueprintet.

1. Pushold ezt a branchet GitHubra, vagy a módosítások merge-elése után válaszd ki a repositoryt Renderben.
2. Renderben: **New → Blueprint** vagy **New Web Service**, repository: `cupcakke/alabama`.
3. Docker runtime esetén a `Dockerfile` automatikusan indul. A `render.yaml` létrehozza az `MCP_AUTH_TOKEN` secretet.
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
      "auth": {
        "type": "bearer",
        "token": "<MCP_AUTH_TOKEN>"
      },
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
      "auth": {
        "type": "bearer",
        "token": "<MCP_AUTH_TOKEN>"
      },
      "allowed_tools": ["search", "fetch"]
    }
  ]
}
JSON
```

A Valyu felületén ugyanezeket az adatokat kell megadni az **MCP server / custom MCP** mezőknél: URL, név, Bearer authentication és a `search`, `fetch` engedélyezése. A token helyére a Render secret pontos értéke kerüljön; a token ne kerüljön Git-be, promptba vagy nyilvános issue-ba.

Használható kutatási utasítás:

> Először mindig hívd meg az `alabama.search` eszközt a releváns iratok azonosítására, majd az eredmények `id` értékeivel hívd meg az `alabama.fetch` eszközt. Ne próbáld a dokumentumokat a fájlnevek alapján összefoglalni. Csak a lekért szöveg alapján állíts tényt, és a válaszban használd a visszaadott citation URL-eket.

## Környezeti változók

| Változó | Alapértelmezett | Leírás |
| --- | --- | --- |
| `MCP_AUTH_TOKEN` | üres | Bearer token remote HTTP védelemhez. Productionben állítsd be. |
| `MCP_ROOT` | `server.py` könyvtára | A beolvasandó repository-gyökér. Dockerben `/app`. |
| `PORT` | `8000` | HTTP port; a legtöbb PaaS felülírja. |
| `PUBLIC_BASE_URL` | üres | Ha megadod, a citation URL-ek ezt a hostot használják. |
| `CITATION_BASE_URL` | GitHub `main` blob URL | Fallback citation host. Állítsd a tényleges adatbranchre. |
| `MAX_SEARCH_RESULTS` | `10` | A kompatibilis `search` legfeljebb ennyi találatot ad. |
| `MAX_FETCH_CHARS` | `2,000,000` | Biztonsági válaszlimit; a jelenlegi legnagyobb fájl ennél kisebb. |
| `MCP_ALLOW_QUERY_TOKEN` | `false` | Ne engedélyezd URL queryben a tokent, mert logokba kerülhet. |

## Biztonsági megjegyzések

- Csak `.md` fájlok olvashatók; a `.git`, virtualenv és symlinkek ki vannak zárva.
- A `fetch` és a helper eszközök nem engednek path traversal-t (`../`) és nem írnak lemezre.
- A dokumentumok tartalma prompt injectiont is tartalmazhat. A Valyu kutatási utasításában kezeld az iratokat adatként, ne végrehajtandó utasításként.
- A szerver lokálisan token nélkül is fut a könnyebb tesztelés miatt. Nyilvános deploy előtt állíts be `MCP_AUTH_TOKEN`-t, és ellenőrizd a `/health` választ.
