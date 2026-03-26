# m100api

FastAPI backend for Cloud Run with QR code generation and upload to:

- `gs://m100boosters/media/qrcodes`

## Endpoints

- `GET /health`
- `GET /status`
- `POST /qrcreate`

### `POST /qrcreate` body

```json
{
  "url": "https://example.com",
  "style": 1,
  "box_size": 10,
  "border": 4,
  "error_correction": "M",
  "fill_color": "black",
  "back_color": "white",
  "fit": true,
  "output_size": 1200
}
```

`style` values:

- `1` = basic QR code
- `2` = logo style (center logo from `gs://m100boosters/media/logos/m100_qr_logo_v1_black.png` at ~30% width)

Example response:

```json
{
  "ok": true,
  "source_url": "https://example.com",
  "gcs_uri": "gs://m100boosters/media/qrcodes/<uuid>.png",
  "public_url": "https://storage.googleapis.com/m100boosters/media/qrcodes/<uuid>.png"
}
```

## Local setup (venv)

```bash
cd m100api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Test:

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/status
curl -X POST http://127.0.0.1:8080/qrcreate \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}'
```

## Cloud Run deploy

```bash
gcloud run deploy m100api \
  --source . \
  --region us-central1 \
  --allow-unauthenticated
```

## IAM / bucket notes

The Cloud Run service account must be able to write objects to the bucket:

- `roles/storage.objectCreator` (minimum)
- Optional for overwrite/delete flows: `roles/storage.objectAdmin`

If object ACLs are disabled (Uniform Bucket-Level Access), ensure bucket-level IAM grants public read if you want `public_url` to be accessible anonymously.
