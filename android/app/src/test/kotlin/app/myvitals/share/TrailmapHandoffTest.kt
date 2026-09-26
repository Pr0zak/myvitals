package app.myvitals.share

import android.app.PendingIntent
import android.content.Intent
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The pure half of "Send to trailmap". The PackageManager calls need a
 * device; what decides whether the key may leave, and what gets logged,
 * does not. Invented addresses throughout.
 */
class TrailmapHandoffTest {

    @Test fun pinDecodesTo32Bytes() {
        val b = TrailmapHandoff.decodeSha256Pin(TrailmapHandoff.RELEASE_CERT_SHA256)
        assertEquals(32, b.size)
        assertEquals(0x0a.toByte(), b[0])
        assertEquals(0xea.toByte(), b[1])
        assertEquals(0xd4.toByte(), b[31])
    }

    @Test fun pinRoundTripsToTheSameHex() {
        val b = TrailmapHandoff.decodeSha256Pin(TrailmapHandoff.RELEASE_CERT_SHA256)
        assertEquals(TrailmapHandoff.RELEASE_CERT_SHA256, b.joinToString("") { "%02x".format(it) })
    }

    @Test fun pinIsCaseInsensitive() {
        val pin = TrailmapHandoff.RELEASE_CERT_SHA256
        assertArrayEquals(
            TrailmapHandoff.decodeSha256Pin(pin),
            TrailmapHandoff.decodeSha256Pin(pin.uppercase()),
        )
    }

    @Test fun pinBoundaryBytes() {
        val b = TrailmapHandoff.decodeSha256Pin("00".repeat(31) + "ff")
        assertEquals(0, b[0].toInt())
        assertEquals(0xff.toByte(), b[31])
    }

    @Test fun malformedPinsAreRejected() {
        val good = TrailmapHandoff.RELEASE_CERT_SHA256
        for (bad in listOf(
            "",
            good.dropLast(1),                       // 63 chars
            good + "0",                             // 65 chars
            good.dropLast(2) + "zz",                // not hex
            good.chunked(2).joinToString(":").take(64), // keytool colon form
        )) {
            assertThrows(bad) { TrailmapHandoff.decodeSha256Pin(bad) }
        }
    }

    @Test fun contractStrings() {
        assertEquals("com.trailmap", TrailmapHandoff.PACKAGE)
        assertEquals("com.trailmap.action.CONNECT_MYVITALS", TrailmapHandoff.ACTION)
        assertEquals("com.trailmap.extra.MYVITALS_URL", TrailmapHandoff.EXTRA_URL)
        assertEquals("com.trailmap.extra.MYVITALS_TOKEN", TrailmapHandoff.EXTRA_TOKEN)
        assertEquals("com.trailmap.extra.MYVITALS_SENDER", TrailmapHandoff.EXTRA_SENDER)
    }

    /**
     * The offer carries exactly the contract: trailmap's action, pinned to
     * its package, the address, the key and the sender proof, and nothing
     * else. The Intent is layoutlib's real class (Paparazzi puts it on the
     * test classpath); the PendingIntent is a stand-in, see [fakeSender].
     */
    @Test fun offerCarriesExactlyTheContract() {
        val sender = fakeSender()
        val i = TrailmapHandoff.offerIntent(
            "https://vitals.example.com", "example-token-0000", sender,
        )
        assertEquals(TrailmapHandoff.ACTION, i.action)
        assertEquals(TrailmapHandoff.PACKAGE, i.`package`)
        assertNull("package-pinned, not a component", i.component)
        assertTrue(i.flags and Intent.FLAG_ACTIVITY_NEW_TASK != 0)
        assertEquals("https://vitals.example.com", i.getStringExtra(TrailmapHandoff.EXTRA_URL))
        assertEquals("example-token-0000", i.getStringExtra(TrailmapHandoff.EXTRA_TOKEN))
        assertSame(sender, i.getParcelableExtra(TrailmapHandoff.EXTRA_SENDER, PendingIntent::class.java))
        assertEquals(
            setOf(TrailmapHandoff.EXTRA_URL, TrailmapHandoff.EXTRA_TOKEN, TrailmapHandoff.EXTRA_SENDER),
            i.extras!!.keySet(),
        )
    }

    /** A refusal can go stale while trailmap is updated; "Sent" is read on the way back. */
    @Test fun resumeDropsRefusalsAndKeepsSentForOneReturn() {
        // Coming back from trailmap is the first resume: "Sent" is read then.
        assertSame(TrailmapHandoff.Result.Sent,
            TrailmapHandoff.resultAfterResume(TrailmapHandoff.Result.Sent, 1))
        // Any later return, it would be claiming an old send.
        assertNull(TrailmapHandoff.resultAfterResume(TrailmapHandoff.Result.Sent, 2))
        assertNull(TrailmapHandoff.resultAfterResume(null, 1))
        for (r in listOf(
            TrailmapHandoff.Result.NotConfigured, TrailmapHandoff.Result.NotInstalled,
            TrailmapHandoff.Result.Untrusted, TrailmapHandoff.Result.CantReceive,
            TrailmapHandoff.Result.Blocked,
        )) assertNull(r.toString(), TrailmapHandoff.resultAfterResume(r, 1))
    }

    @Test fun sentMessageFitsConnectAndUseThis() {
        // trailmap shows "Connect" when new and "Use this" when already
        // connected, so the message names neither button.
        assertEquals(
            "Sent. Check the details in trailmap and confirm there.",
            TrailmapHandoff.Result.Sent.message,
        )
    }

    @Test fun logLineCarriesTheHostOnly() {
        assertEquals("vitals.example.com", TrailmapHandoff.hostOf("https://vitals.example.com"))
        assertEquals("vitals.example.com", TrailmapHandoff.hostOf("https://vitals.example.com:8443/api/"))
        // A user:password in the address must never reach the log. Built
        // from parts so the public-repo scanner doesn't read the fixture as
        // a real credential.
        val withUserInfo = "https://" + "someone:placeholder" + "@vitals.example.com/"
        assertEquals("vitals.example.com", TrailmapHandoff.hostOf(withUserInfo))
        assertEquals("vitals.example.com", TrailmapHandoff.hostOf("  vitals.example.com  "))
        assertEquals("unknown host", TrailmapHandoff.hostOf(""))
        assertEquals("unknown host", TrailmapHandoff.hostOf("not an address"))
    }

    @Test fun buttonIsOffUntilTheSavedConnectionIsWhatsOnScreen() {
        assertNull(TrailmapHandoff.blockedReason(configured = true, unsavedEdits = false))
        assertEquals("Save your server first",
            TrailmapHandoff.blockedReason(configured = true, unsavedEdits = true))
        assertEquals("Save your server first",
            TrailmapHandoff.blockedReason(configured = false, unsavedEdits = true))
        assertEquals("Set up your server first",
            TrailmapHandoff.blockedReason(configured = false, unsavedEdits = false))
    }

    @Test fun onlySentCountsAsSuccess() {
        assertTrue(TrailmapHandoff.Result.Sent.ok)
        for (r in listOf(
            TrailmapHandoff.Result.NotConfigured, TrailmapHandoff.Result.NotInstalled,
            TrailmapHandoff.Result.Untrusted, TrailmapHandoff.Result.CantReceive,
            TrailmapHandoff.Result.Blocked,
        )) assertFalse(r.toString(), r.ok)
        assertEquals(
            "The trailmap on this phone isn't the official build, so your key wasn't sent.",
            TrailmapHandoff.Result.Untrusted.message,
        )
    }

    /**
     * A PendingIntent without a system to create it. layoutlib's class
     * takes its IIntentSender directly (a constructor the SDK hides, hence
     * reflection); the proxy answers nothing, and nothing here calls it.
     */
    private fun fakeSender(): PendingIntent {
        val iface = Class.forName("android.content.IIntentSender")
        val target = java.lang.reflect.Proxy.newProxyInstance(iface.classLoader, arrayOf(iface)) { proxy, m, args ->
            when (m.name) {
                "hashCode" -> System.identityHashCode(proxy)
                "equals" -> proxy === args?.get(0)
                "toString" -> "fake IIntentSender"
                else -> null
            }
        }
        return PendingIntent::class.java.getConstructor(iface).newInstance(target)
    }

    private fun assertThrows(input: String, block: () -> Unit) {
        try {
            block()
        } catch (e: IllegalArgumentException) {
            return
        }
        throw AssertionError("expected IllegalArgumentException for \"$input\"")
    }
}
