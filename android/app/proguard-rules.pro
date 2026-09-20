# Keep Moshi-generated adapters. SA-C1: this was dead code while
# isMinifyEnabled was false — it now actually runs. Moshi codegen also
# emits its own precise per-class -if/-keep pair under
# app/build/generated/ksp/*/resources/META-INF/proguard/, which R8 picks
# up automatically; this wildcard is the defense-in-depth backstop.
-keep class **.*JsonAdapter { *; }
-keepclassmembers class kotlin.Metadata { *; }
