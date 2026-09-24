package app.myvitals.update

import app.myvitals.BuildConfig

object UpdateChecker {

    /** Returns the release if a newer version is available, else null. */
    suspend fun checkForUpdate(currentVersion: String = BuildConfig.VERSION_NAME): GitHubRelease? {
        val (owner, repo) = BuildConfig.GITHUB_REPO.split("/", limit = 2)
            .let { it[0] to it[1] }

        val release = try {
            GitHub.api.latestRelease(owner, repo)
        } catch (e: Exception) {
            return null
        }

        val latest = release.tagName.removePrefix("v").trim()
        return if (isNewer(latest, currentVersion)) release else null
    }

    /** SETTINGS-C — the outcome of a user-initiated check, where "could not
     *  reach GitHub" must not read as "up to date" (failure is not absence;
     *  [checkForUpdate] folds both into null, which is fine for the silent
     *  background worker and wrong on a screen that says "Up to date"). */
    sealed class Result {
        object UpToDate : Result()
        data class Available(val release: GitHubRelease) : Result()
        data class Failed(val message: String) : Result()
    }

    suspend fun check(currentVersion: String = BuildConfig.VERSION_NAME): Result {
        val (owner, repo) = BuildConfig.GITHUB_REPO.split("/", limit = 2)
            .let { it[0] to it[1] }
        val release = try {
            GitHub.api.latestRelease(owner, repo)
        } catch (e: Exception) {
            return Result.Failed(e.message?.take(120) ?: e.javaClass.simpleName)
        }
        val latest = release.tagName.removePrefix("v").trim()
        return if (isNewer(latest, currentVersion)) Result.Available(release) else Result.UpToDate
    }

    /** Naive semver compare on the leading numeric parts. */
    fun isNewer(latest: String, current: String): Boolean {
        val l = parseParts(latest)
        val c = parseParts(current)
        for (i in 0 until maxOf(l.size, c.size)) {
            val a = l.getOrElse(i) { 0 }
            val b = c.getOrElse(i) { 0 }
            if (a != b) return a > b
        }
        return false
    }

    private fun parseParts(version: String): List<Int> =
        version.split('.', '-', '+')
            .mapNotNull { it.toIntOrNull() }
}
