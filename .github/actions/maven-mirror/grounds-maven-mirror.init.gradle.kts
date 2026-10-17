// Points the public upstream repositories at the CI runners' Maven mirror.
// Installed by the groundsgg/.github maven-mirror action on self-hosted runners only.
// GitHub Packages, mavenLocal() and every other repository stay as the build declares them.
//
// The mirror is plain HTTP inside the cluster, so only the rewritten repositories get
// isAllowInsecureProtocol.

val mirror = "@MIRROR_URL@".trimEnd('/')
val pluginPortal = "https://plugins.gradle.org/m2"
val rewrites = mapOf(
    "https://repo.maven.apache.org/maven2" to "$mirror/releases",
    "https://repo1.maven.org/maven2" to "$mirror/releases",
    pluginPortal to "$mirror/gradle-plugins",
    "https://repo.papermc.io/repository/maven-public" to "$mirror/papermc",
)

fun RepositoryHandler.useMirror() {
    whenObjectAdded {
        val repo = this as? MavenArtifactRepository ?: return@whenObjectAdded
        val upstream = repo.url.toString().trimEnd('/')
        val target = rewrites[upstream] ?: return@whenObjectAdded
        if (upstream == pluginPortal) {
            // gradlePluginPortal() is a repository Gradle builds itself; swap it for a plain
            // maven repository rather than mutating it. Adding here keeps its place in the list.
            remove(repo)
            maven {
                name = "groundsMavenMirrorGradlePlugins"
                url = uri(target)
                isAllowInsecureProtocol = true
            }
        } else {
            repo.url = uri(target)
            repo.isAllowInsecureProtocol = true
        }
    }
}

println("Using Maven mirror $mirror")

beforeSettings {
    buildscript.repositories.useMirror()
    pluginManagement.repositories.useMirror()
    dependencyResolutionManagement.repositories.useMirror()
}

settingsEvaluated {
    // Without any pluginManagement repositories Gradle falls back to an implicit plugin portal
    // that never enters this list; declare it so it gets swapped for the mirror.
    if (pluginManagement.repositories.isEmpty()) pluginManagement.repositories.gradlePluginPortal()
}

allprojects {
    buildscript.repositories.useMirror()
    repositories.useMirror()
}
