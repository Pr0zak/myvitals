# Releasing & upgrades

How a new release of myvitals goes from `git tag` → backend image on GHCR → signed APK on GitHub Releases → installed everywhere.

## One-time setup

### 1. Android signing keystore

The same keystore must sign every release. Lose it and you cannot ship updates that install over previous versions — users have to uninstall + reinstall.

```bash
# Run anywhere; keep the .jks OUTSIDE the repo.
keytool -genkey -v \
  -keystore ~/.android-keys/myvitals-release.jks \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -alias myvitals
```

Back up `~/.android-keys/myvitals-release.jks` somewhere safe (password manager attachment, encrypted backup).

### 2. Local signing config

```bash
cp android/keystore.properties.example android/keystore.properties
$EDITOR android/keystore.properties
```

Both `keystore.properties` and `*.jks` are gitignored.

### 3. GitHub Secrets (for CI)

Settings → Secrets and variables → Actions → New repository secret. Add four:

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_B64` | `base64 -w0 ~/.android-keys/myvitals-release.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | the store password from step 1 |
| `ANDROID_KEY_ALIAS` | `myvitals` |
| `ANDROID_KEY_PASSWORD` | the key password from step 1 |

Without these, the `android release` workflow fails fast with a clear error.

The backend/frontend image workflow needs no secrets — `GITHUB_TOKEN` is automatic and grants write access to the repo's GHCR namespace.

### 4. Make GHCR images public (one-time, optional)

By default the first push to GHCR creates **private** packages. To let the CT pull without auth: go to your profile → Packages → `myvitals-backend` and `myvitals-frontend` → Package settings → Change visibility → Public.

If you keep them private, `docker login ghcr.io` with a PAT is required on the CT.

### 5. CT bootstrap

```bash
# On the CT (root):
cd /opt && git clone https://github.com/Pr0zak/myvitals.git
cd myvitals
cp .env.example .env
$EDITOR .env   # set INGEST_TOKEN, QUERY_TOKEN, POSTGRES_PASSWORD via `openssl rand -hex 32`
./deploy/ct-bootstrap.sh
```

## Cutting a release

```bash
# from main, on dev box:
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
```

That single push triggers two workflows in parallel:

- `images.yml` → builds + pushes `ghcr.io/pr0zak/myvitals-backend:0.2.0`, `:0.2`, `:latest`, and `:sha-XXXXXXX` (same for frontend).
- `android-release.yml` → builds signed APK with versionName `0.2.0`, uploads to the GitHub Release as `myvitals-0.2.0.apk` plus `.sha256`.

The Release itself is created by the Android workflow (auto-generated notes from commit history).

### Versioning

Tags drive everything. The Android `versionName` is set from the tag (strip leading `v`). The Android `versionCode` is the workflow run number — monotonically increasing per CI run, so updates always supersede.

Backend version is read at runtime from `pyproject.toml`'s `[project] version`. Bump it in the same commit you tag, or accept that `/version` will show the previous value until the next bump.

## Server upgrade

On the CT:

```bash
cd /opt/myvitals
./deploy/upgrade.sh                  # pulls latest tag, restarts, verifies /version
./deploy/upgrade.sh 0.2.0            # pin to a specific version
./deploy/upgrade.sh --rebuild        # build from local source instead of pulling
```

Migrations run automatically on backend container start (`alembic upgrade head` in the `CMD`).

### Rollback

```bash
./deploy/upgrade.sh 0.1.0   # pin to previous tag
```

Note: this does NOT downgrade the database schema. If a release ships breaking migrations, downgrading the image alone is unsafe — restore from a DB backup taken before the upgrade.

### Cron (optional)

```cron
# /etc/cron.d/myvitals-upgrade — every Sunday at 04:00
0 4 * * 0 root cd /opt/myvitals && ./deploy/upgrade.sh >> /var/log/myvitals-upgrade.log 2>&1
```

## Android upgrade

### First install (sideload)

1. On the phone, enable "Install unknown apps" for your browser (Settings → Apps → Chrome → Install unknown apps).
2. Visit https://github.com/Pr0zak/myvitals/releases, download the latest `.apk`.
3. Open the file → Android prompts to install → done.

After the first install, future updates can use the in-app updater (next section).

### Auto-check

The app schedules a daily WorkManager job (`UpdateCheckWorker`) that hits the GitHub Releases API. When a newer tag is available it posts a notification: tap → app downloads APK → triggers the system installer.

The installer prompts you to enable "Install unknown apps" for myvitals itself the first time.

### Manual check

Settings screen → "Check for updates" button.

### Bootstrap APK (before CI is set up)

If you don't want to wait on CI for the first build, build a debug APK in Android Studio (`Build → Build APK(s)`). The debug-signed APK installs and runs fine but **cannot** be updated by a release-signed APK later — Android rejects it as a different signing identity. So either:

- Use the debug APK only for prototyping; uninstall before installing the first release APK; **or**
- Set up signing + CI first, build a release APK locally with `cd android && ./gradlew :app:assembleRelease`, sideload that.

## Workflow files

- `.github/workflows/images.yml` — backend + frontend Docker images on push to main and on tags.
- `.github/workflows/android-release.yml` — signed APK release on tags only.
