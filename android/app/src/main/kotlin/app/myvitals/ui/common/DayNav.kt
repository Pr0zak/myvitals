package app.myvitals.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.ui.MV
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Compact day picker: ← [Wed, May 13] →
 * - Left arrow steps back one day.
 * - Right arrow steps forward, disabled when already at today.
 * - Tapping the label opens a Material3 DatePicker.
 *
 * Used on detail screens that render a single day of data so the user
 * can scroll history without losing the day-of view.
 *
 * TD-3 gave the web a matching `DayNav.vue`, and brought back the one idea
 * this control was missing: while the selected day is not today, the pill
 * takes a visible tint and grows a Today chip. Being parked on last Tuesday
 * and reading the numbers as though they were current is a real failure
 * mode, and one small unstyled label is not enough to prevent it. (The web
 * additionally tints the whole nav chrome via a `data-day-relation` stamp on
 * the document; there is no equivalent hook into the Compose shell from
 * here, so that half is web-only for now.)
 */
/** Amber, matching the web's `--warn`-derived past-day edge. */
private val OFF_TODAY_TINT = androidx.compose.ui.graphics.Color(0xFFEAB308)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DayNav(
    selected: LocalDate,
    onSelectedChange: (LocalDate) -> Unit,
    modifier: Modifier = Modifier,
    showTodayShortcut: Boolean = true,
) {
    val today = LocalDate.now()
    val isToday = selected == today
    val labelFmt = remember { DateTimeFormatter.ofPattern("EEE, MMM d") }
    val label = if (isToday) "Today" else selected.format(labelFmt)
    var showPicker by remember { mutableStateOf(false) }

    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp)
            .then(
                if (isToday) Modifier
                else Modifier
                    .clip(RoundedCornerShape(999.dp))
                    .border(1.dp, OFF_TODAY_TINT.copy(alpha = 0.55f), RoundedCornerShape(999.dp))
                    .background(OFF_TODAY_TINT.copy(alpha = 0.06f)),
            ),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        IconButton(onClick = { onSelectedChange(selected.minusDays(1)) }) {
            Icon(
                Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = "Previous day",
                tint = MV.OnSurface,
            )
        }
        TextButton(onClick = { showPicker = true }) {
            Text(
                label,
                color = MV.OnSurface,
                fontSize = 14.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
        IconButton(
            onClick = { onSelectedChange(selected.plusDays(1)) },
            enabled = !isToday,
        ) {
            Icon(
                Icons.AutoMirrored.Filled.ArrowForward,
                contentDescription = "Next day",
                tint = if (isToday) MV.OnSurfaceDim else MV.OnSurface,
            )
        }
        // One tap back to now, and a standing reminder that you are not
        // there. Mirrors the web control's Today chip.
        if (!isToday && showTodayShortcut) {
            TextButton(onClick = { onSelectedChange(today) }) {
                Text(
                    "TODAY",
                    color = OFF_TODAY_TINT,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 0.8.sp,
                )
            }
        }
    }

    if (showPicker) {
        DayPickerDialog(
            initial = selected,
            onPick = { onSelectedChange(it); showPicker = false },
            onDismiss = { showPicker = false },
            todayShortcut = showTodayShortcut,
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DayPickerDialog(
    initial: LocalDate,
    onPick: (LocalDate) -> Unit,
    onDismiss: () -> Unit,
    todayShortcut: Boolean,
) {
    val zone = ZoneId.systemDefault()
    val initialMs = initial.atStartOfDay(zone).toInstant().toEpochMilli()
    val todayEpoch = LocalDate.now().atStartOfDay(zone).toInstant().toEpochMilli()
    val state = rememberDatePickerState(
        initialSelectedDateMillis = initialMs,
        selectableDates = object : SelectableDates {
            override fun isSelectableDate(utcTimeMillis: Long): Boolean =
                utcTimeMillis <= todayEpoch + 86_400_000L  // tomorrow midnight cap
        },
    )
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Pick a day") },
        text = { DatePicker(state = state) },
        confirmButton = {
            TextButton(onClick = {
                val ms = state.selectedDateMillis
                if (ms != null) {
                    val date = java.time.Instant.ofEpochMilli(ms).atZone(zone).toLocalDate()
                    onPick(date)
                } else onDismiss()
            }) { Text("OK") }
        },
        dismissButton = {
            Row {
                if (todayShortcut) {
                    TextButton(onClick = { onPick(LocalDate.now()) }) { Text("Today") }
                }
                TextButton(onClick = onDismiss) { Text("Cancel") }
            }
        },
    )
}
