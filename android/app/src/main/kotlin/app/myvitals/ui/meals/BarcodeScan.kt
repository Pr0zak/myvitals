package app.myvitals.ui.meals

import android.content.Context
import com.google.android.gms.common.moduleinstall.ModuleInstall
import com.google.android.gms.common.moduleinstall.ModuleInstallRequest
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScanner
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning

/**
 * Scanning a product barcode.
 *
 * Uses Google's Code Scanner rather than raw ML Kit or a hand-rolled
 * camera preview, for three reasons that all point the same way: it
 * ships its own scanning UI, it needs no CAMERA permission at all — so
 * there is no runtime prompt to explain — and its model arrives through
 * Play Services instead of adding megabytes to the APK.
 *
 * The formats are restricted to the ones printed on food. A scanner that
 * also reads QR codes will happily return the URL on the back of the
 * packet, which is not a barcode lookup and only wastes a request.
 */
internal object BarcodeScan {

    private val options = GmsBarcodeScannerOptions.Builder()
        .setBarcodeFormats(
            Barcode.FORMAT_EAN_13,
            Barcode.FORMAT_EAN_8,
            Barcode.FORMAT_UPC_A,
            Barcode.FORMAT_UPC_E,
        )
        .enableAutoZoom()
        .build()

    fun scanner(context: Context): GmsBarcodeScanner =
        GmsBarcodeScanning.getClient(context, options)

    /**
     * Ask Play Services to fetch the scanner module ahead of time.
     *
     * Without this the first scan of the app's life stalls on a silent
     * download while the user stares at a button that did nothing. It is
     * a hint, not a requirement: failure is ignored because the scan path
     * downloads on demand anyway, just less pleasantly.
     */
    fun warmUp(context: Context) {
        runCatching {
            ModuleInstall.getClient(context).installModules(
                ModuleInstallRequest.newBuilder()
                    .addApi(scanner(context))
                    .build(),
            )
        }
    }
}
