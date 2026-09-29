package app.myvitals.ui.trails

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.Units
import app.myvitals.sync.OtherTrail
import app.myvitals.sync.Trail
import app.myvitals.sync.TrailSuggestionsResponse
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV

/** Where the suggestion fetch stands. [response] is null until it lands. */
data class TrailSuggestState(
    val loading: Boolean = true,
    val response: TrailSuggestionsResponse? = null,
    val failed: Boolean = false,
)

/**
 * The body of both "Link to trail" sheets: the server's suggestions first
 * (OSM trails the route ran along, then status-board pins near it), then
 * every pinned trail and every already-linked OSM trail A→Z. The
 * suggested trails also stay in the full list, so nothing moves out of its
 * alphabetical place for someone who knows where to look.
 */
/** What a tap links to: an existing trails row, or an OSM trail not yet linked. */
data class TrailPick(val trailId: Long?, val osmTrailId: Long? = null)

/** A row of the A→Z list — status-board trails and linked OSM trails alike. */
private data class ListRow(val id: Long, val name: String, val place: String)

@Composable
fun TrailPickerList(
    trails: List<Trail>,
    otherTrails: List<OtherTrail>,
    suggest: TrailSuggestState,
    currentTrailId: Long?,
    enabled: Boolean,
    rowColor: Color,
    onPick: (TrailPick) -> Unit,
) {
    val pickable = (
        trails.filter { it.latitude != null && it.longitude != null }
            .map { ListRow(it.id, it.name, listOfNotNull(it.city, it.state).joinToString(", ")) } +
        otherTrails.map { ListRow(it.id, it.name, listOfNotNull(it.city, it.state).joinToString(", ")) }
    ).sortedBy { it.name }
    val suggestions = suggest.response?.suggestions.orEmpty()
    // Always say what the suggestion lookup did, so an empty section is
    // never mistaken for "still loading" or the reverse.
    val status = when {
        suggest.loading -> "Finding trails near this route…"
        suggest.failed -> "Couldn't load suggestions — pick from the list."
        suggest.response?.hasGps == false -> "No GPS route on this activity — pick from the list."
        suggestions.isEmpty() -> "No known trail along this route or within " +
            Units.fmtDistance((suggest.response?.maxKm ?: 10.0) * 1000.0, digits = 0) +
            " of it."
        else -> null
    }
    // Status and suggestions sit ABOVE the scrolling list, not inside it.
    // As LazyColumn items they arrived after the list had rendered, and a
    // LazyColumn keeps its first visible item anchored when rows are
    // inserted before it — so they landed just off the top and the user
    // had to scroll up to find them (v0.50.4).
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        if (status != null) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically) {
                if (suggest.loading) {
                    CircularProgressIndicator(Modifier.size(14.dp), color = NeonMV.Cyan, strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text(status, color = NeonMV.Muted, fontSize = 12.sp)
            }
        }
        if (suggestions.isNotEmpty()) {
            NeonEyebrow("Suggested · nearest to this route")
            suggestions.forEach { s ->
                PickRow(
                    name = s.name,
                    // A trail the route ran along says how much of the ride was
                    // on it; a status-board pin says how far away it was.
                    trailing = s.onTrailKm?.let { Units.fmtDistance(it * 1000.0) + " on it" }
                        ?: (Units.fmtDistance(s.distanceKm * 1000.0) + " away"),
                    current = s.trailId != null && s.trailId == currentTrailId,
                    enabled = enabled,
                    color = NeonMV.Lime.copy(alpha = 0.10f),
                ) { onPick(TrailPick(s.trailId, s.osmTrailId)) }
            }
        }
        NeonEyebrow("All trails")
    }
    LazyColumn(
        Modifier.fillMaxWidth().height(if (suggestions.isNotEmpty()) 240.dp else 320.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        items(pickable, key = { it.id }) { t ->
            PickRow(
                name = t.name,
                trailing = t.place,
                current = t.id == currentTrailId,
                enabled = enabled,
                color = rowColor,
            ) { onPick(TrailPick(t.id)) }
        }
    }
}

@Composable
private fun PickRow(
    name: String,
    trailing: String,
    current: Boolean,
    enabled: Boolean,
    color: Color,
    onClick: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (current) NeonMV.Cyan.copy(alpha = 0.15f) else color,
        ),
        modifier = Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onClick),
    ) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text(name, modifier = Modifier.weight(1f), color = NeonMV.Ink, fontSize = 14.sp)
            if (trailing.isNotEmpty()) Text(trailing, color = NeonMV.Muted, fontSize = 11.sp)
        }
    }
}
