package app.myvitals.debug

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import app.myvitals.ui.MyVitalsTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.platform.LocalContext
import app.myvitals.data.AppDatabase
import app.myvitals.data.LogEntry
import kotlinx.coroutines.launch
import timber.log.Timber
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class LogViewerActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MyVitalsTheme { LogViewerScreen() } }
    }

    companion object {
        fun start(activity: ComponentActivity) {
            activity.startActivity(Intent(activity, LogViewerActivity::class.java))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LogViewerScreen() {
    val context = LocalContext.current
    val db = remember { AppDatabase.get(context) }
    val scope = rememberCoroutineScope()
    val logs by db.logs().recentFlow().collectAsState(initial = emptyList())
    var levelFilter by remember { mutableIntStateOf(android.util.Log.VERBOSE) }

    val visible = remember(logs, levelFilter) { logs.filter { it.level >= levelFilter } }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Logs (${visible.size})") },
                actions = {
                    TextButton(onClick = {
                        scope.launch {
                            db.logs().clear()
                            Timber.i("Logs cleared by user")
                        }
                    }) { Text("Clear") }
                }
            )
        }
    ) { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxSize()) {
            FilterRow(
                current = levelFilter,
                onChange = { levelFilter = it },
            )
            HorizontalDivider()
            LazyColumn(modifier = Modifier.weight(1f)) {
                items(visible, key = { it.id }) { entry -> LogRow(entry) }
                if (visible.isEmpty()) {
                    item {
                        Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = androidx.compose.ui.Alignment.Center) {
                            Text("No logs yet at this level.", color = Color.Gray)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun FilterRow(current: Int, onChange: (Int) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(8.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        listOf(
            android.util.Log.VERBOSE to "V",
            android.util.Log.DEBUG to "D",
            android.util.Log.INFO to "I",
            android.util.Log.WARN to "W",
            android.util.Log.ERROR to "E",
        ).forEach { (level, label) ->
            FilterChip(
                selected = current == level,
                onClick = { onChange(level) },
                label = { Text(label) },
            )
        }
    }
}

@Composable
private fun LogRow(entry: LogEntry) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(rowColor(entry.level))
            .padding(horizontal = 8.dp, vertical = 4.dp)
    ) {
        Text(
            text = "${formatTime(entry.tsEpochMs)} ${levelChar(entry.level)}/${entry.tag ?: "-"}: ${entry.message}",
            fontFamily = FontFamily.Monospace,
            fontSize = 11.sp,
            color = Color(0xFFE2E8F0),
        )
        entry.stack?.let { stack ->
            Text(
                text = stack,
                fontFamily = FontFamily.Monospace,
                fontSize = 10.sp,
                color = Color(0xFFEF4444),
                modifier = Modifier.padding(top = 2.dp, start = 16.dp),
            )
        }
    }
}

private fun rowColor(level: Int): Color = when (level) {
    android.util.Log.ERROR -> Color(0xFF3F1F1F)
    android.util.Log.WARN -> Color(0xFF3F3F1F)
    else -> Color(0xFF0F172A)
}

private fun levelChar(level: Int): Char = when (level) {
    android.util.Log.VERBOSE -> 'V'
    android.util.Log.DEBUG -> 'D'
    android.util.Log.INFO -> 'I'
    android.util.Log.WARN -> 'W'
    android.util.Log.ERROR -> 'E'
    else -> '?'
}

private val timeFormat = SimpleDateFormat("HH:mm:ss.SSS", Locale.getDefault())
private fun formatTime(epochMs: Long): String = timeFormat.format(Date(epochMs))
