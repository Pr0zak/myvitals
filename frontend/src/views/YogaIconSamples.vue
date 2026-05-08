<script setup lang="ts">
/**
 * Side-by-side comparison of yoga-pose icon sources for the 15 poses
 * shipped in the catalog supplement. Visit at /yoga-icon-samples.
 *
 * Sources compared:
 *   1. Custom (current)  — hand-drawn SVGs in YogaPoseIcon.vue
 *   2. Iconify yoga set  — fluent-emoji "person in lotus" + variants
 *      (fetched live from https://api.iconify.design/, no auth)
 *   3. Twemoji generic   — falls back to 🧘 person-in-lotus for all
 *      since pose-specific emoji don't exist
 *
 * Flaticon would slot in as a 4th column once you've manually
 * downloaded SVGs to backend/src/myvitals/data/yoga-icons/<id>.svg.
 */
import YogaPoseIcon from "@/components/YogaPoseIcon.vue";

const POSES = [
  "Downward_Dog", "Childs_Pose", "Cat_Cow", "Cobra_Pose", "Pigeon_Pose",
  "Forward_Fold", "Warrior_2", "Triangle_Pose", "Seated_Forward_Bend",
  "Reclined_Spinal_Twist", "Bridge_Pose", "Lizard_Pose",
  "Half_Pigeon_Forward_Fold", "Thread_The_Needle", "Happy_Baby",
];

// Iconify lookups — best-fit yoga / person-pose icons. The api returns
// SVG with the requested colour replaced via the ?color= query.
// Verified-existing iconify keys; many resolve to the same lotus-pose
// icon since pose-specific keys are rare in the FOSS sets.
const ICONIFY_LOOKUP: Record<string, string> = {
  Downward_Dog: "fluent-emoji-flat:person-doing-cartwheel",
  Childs_Pose: "fluent-emoji-flat:person-in-lotus-position",
  Cat_Cow: "fluent-emoji-flat:person-doing-cartwheel",
  Cobra_Pose: "fluent-emoji-flat:person-doing-cartwheel",
  Pigeon_Pose: "fluent-emoji-flat:person-running",
  Forward_Fold: "fluent-emoji-flat:person-bowing",
  Warrior_2: "fluent-emoji-flat:person-fencing",
  Triangle_Pose: "fluent-emoji-flat:person-doing-cartwheel",
  Seated_Forward_Bend: "fluent-emoji-flat:person-in-lotus-position",
  Reclined_Spinal_Twist: "fluent-emoji-flat:person-in-bed",
  Bridge_Pose: "fluent-emoji-flat:person-doing-cartwheel",
  Lizard_Pose: "fluent-emoji-flat:person-running",
  Half_Pigeon_Forward_Fold: "fluent-emoji-flat:person-bowing",
  Thread_The_Needle: "fluent-emoji-flat:person-doing-cartwheel",
  Happy_Baby: "fluent-emoji-flat:person-in-bed",
};

function iconifyUrl(id: string, color = "%23a78bfa", size = 56) {
  const key = ICONIFY_LOOKUP[id];
  if (!key) return null;
  return `https://api.iconify.design/${key}.svg?width=${size}&color=${color}`;
}

// OpenMoji yoga emoji — only one true pose icon exists (lotus).
function openmojiUrl(_id: string, size = 56) {
  // 1F9D8 is "Person in lotus position" (gender-neutral)
  return `https://api.iconify.design/openmoji:lotus-position.svg?width=${size}`;
}

// Generic emoji — same all rows
const EMOJI = "🧘";

function pretty(id: string): string {
  return id.replace(/_/g, " ");
}
</script>

<template>
  <main class="samples">
    <h1>Yoga icon source comparison</h1>
    <p class="hint">
      Each row shows the same pose rendered from three free sources.
      Pick the column that's most usable, then we replace
      <code>YogaPoseIcon.vue</code> with the chosen source.
    </p>
    <p class="hint">
      <strong>Flaticon</strong> isn't shown — it requires auth on
      flaticon.com to download. Workflow:
      sign up free, download SVGs into
      <code>backend/src/myvitals/data/yoga-icons/&lt;pose-id&gt;.svg</code>,
      update each yoga catalog row's <code>image_front</code> to
      <code>/exercises/img/yoga/&lt;pose-id&gt;.svg</code>. The catalog
      already prefers <code>image_front</code> over the placeholder, so
      no further wiring is required.
    </p>

    <table class="grid">
      <thead>
        <tr>
          <th class="lbl">Pose</th>
          <th>Custom (current)</th>
          <th>Iconify (Fluent emoji)</th>
          <th>OpenMoji (lotus only)</th>
          <th>Generic emoji</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="id in POSES" :key="id">
          <th class="lbl">{{ pretty(id) }}</th>
          <td>
            <div class="cell">
              <YogaPoseIcon :id="id" :size="56" :stroke="'#a78bfa'"/>
            </div>
          </td>
          <td>
            <div class="cell">
              <img v-if="iconifyUrl(id)" :src="iconifyUrl(id) ?? ''" :alt="id" width="56" height="56"/>
            </div>
          </td>
          <td>
            <div class="cell">
              <img :src="openmojiUrl(id)" :alt="id" width="56" height="56"/>
            </div>
          </td>
          <td>
            <div class="cell emoji">{{ EMOJI }}</div>
          </td>
        </tr>
      </tbody>
    </table>

    <div class="legend">
      <h3>Notes per source</h3>
      <ul>
        <li>
          <strong>Custom</strong> — the SVGs I shipped in v0.7.108. Each
          pose has a distinct silhouette. Free, embedded, no external
          dependency. Limitation: hand-drawn, not artistic.
        </li>
        <li>
          <strong>Iconify (Fluent emoji)</strong> — Microsoft Fluent
          emoji set. Good visual quality; coverage is mostly
          person-pose categories (running, bowing, fencing, in-bed) so
          most rows reuse the cartwheel icon — <em>not</em> per-pose
          distinct in practice.
        </li>
        <li>
          <strong>OpenMoji</strong> — only has the gender-neutral
          lotus pose. Every row shows the same icon — useful only as
          a category marker, not for identification.
        </li>
        <li>
          <strong>Generic emoji 🧘</strong> — single pose, no
          differentiation. Listed for completeness.
        </li>
      </ul>
      <p class="hint">
        <strong>Recommendation:</strong> stick with the custom set
        for now (every pose visually distinct, no external dep).
        Upgrade to a Flaticon yoga pack once you've downloaded the
        15 SVGs — they're hand-illustrated and will look noticeably
        better than the line art.
      </p>
    </div>
  </main>
</template>

<style scoped>
.samples { max-width: 920px; margin: 0 auto; padding: 1.5rem; }
h1 { margin: 0 0 0.6rem; }
.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 0.6rem; }
.hint code {
  background: var(--bg-2); padding: 1px 5px; border-radius: 4px;
  font-family: 'Geist Mono', ui-monospace, monospace; font-size: 0.85em;
}
.grid { width: 100%; border-collapse: collapse; margin-top: 1.4rem; }
.grid th, .grid td {
  border: 1px solid var(--line);
  padding: 0.6rem; text-align: center; vertical-align: middle;
}
.grid th { background: var(--bg-2); font-size: 0.78rem;
           color: var(--muted); font-weight: 600; }
.grid th.lbl { text-align: left; min-width: 11rem;
               color: var(--text); }
.cell { display: flex; align-items: center; justify-content: center;
        height: 64px; }
.cell.emoji { font-size: 2.4rem; }
.legend { margin-top: 2rem; }
.legend h3 { font-size: 0.85rem; letter-spacing: 0.08em;
             text-transform: uppercase; color: var(--muted);
             font-weight: 600; }
.legend ul { padding-left: 1.4rem; }
.legend li { font-size: 0.9rem; line-height: 1.55;
             margin-bottom: 0.6rem; }
.legend strong { color: var(--text); }
.legend em { color: var(--muted); font-style: normal; font-weight: 500; }
</style>
