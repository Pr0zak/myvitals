package app.myvitals.ui.common

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId

/**
 * Material3 24-hour TimePicker wrapped in an AlertDialog. Returns the
 * chosen (hour, minute). Used by the cardio-log and activity-edit
 * dialogs so the "Ended at" field is a real clock picker — matching
 * the web's native <input type="time">.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EndedTimePickerDialog(
    initialHour: Int,
    initialMinute: Int,
    onConfirm: (hour: Int, minute: Int) -> Unit,
    onDismiss: () -> Unit,
) {
    val state = rememberTimePickerState(
        initialHour = initialHour,
        initialMinute = initialMinute,
        is24Hour = true,
    )
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Ended at") },
        text = { TimePicker(state = state) },
        confirmButton = {
            TextButton(onClick = { onConfirm(state.hour, state.minute) }) {
                Text("OK")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}

/**
 * Compose an "ended at" Instant from a user-picked HH:MM. When
 * `anchorDate` is null we anchor to today and roll back a day if the
 * picked time is in the future (user picks 11 PM at 1 AM). When
 * editing an existing activity we anchor to that activity's original
 * date so a 3-day-old entry doesn't jump to today.
 */
fun composeEndedInstant(
    hour: Int,
    minute: Int,
    anchorDate: LocalDate? = null,
): Instant {
    val zone = ZoneId.systemDefault()
    val date = anchorDate ?: LocalDate.now(zone)
    val ldt = LocalDateTime.of(date, LocalTime.of(hour, minute))
    val instant = ldt.atZone(zone).toInstant()
    return if (anchorDate == null && instant.isAfter(Instant.now())) {
        instant.minusSeconds(86_400)
    } else instant
}
