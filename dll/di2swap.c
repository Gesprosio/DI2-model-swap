/* di2swap.dll - the Dead Island 2 model swap, from inside the game. It sits next to the game's exe
 * and is loaded by the DI2ZombieModels UE4SS mod (package.loadlib("di2swap.dll")); swaps.txt and
 * di2swap.log are next to it. Same work as tools/runtime_swap.py, without an external process:
 *
 *  1. reads swaps.txt (written by the mod launcher, next to this dll):
 *       base <n>                                   Walker/Shambler swaps (they always have a bundle)
 *       <variant>|<variant mesh object path>|<mesh object path to use>
 *  2. resolves those names to FNames through the game's FNamePool;
 *  3. at the main menu, in the AssetManager bundle table, the "CharacterMesh" bundle of each variant
 *     lists the new mesh, so the game itself loads it;
 *  4. then watches GUObjectArray: each ModelVariantAsset listed gets its Model soft pointer set to the
 *     new mesh as soon as it is deserialized (object layout: Model FSoftObjectPtr @+0x50, path @+0x60).
 *
 * Memory is read with ReadProcessMemory on this very process, which fails instead of crashing when a
 * page is gone; only the GUObjectArray chunk tables (never freed) are read directly.
 * Log: di2swap.log next to the dll. Build: tools/di2swap/build.bat (w64devkit gcc).
 */
#include <windows.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* this game build (verified at run time, searched again if they do not match) */
#define NAMEPOOL_BLOCKS_RVA 114248848u   /* FNamePool Blocks[] */
#define OBJOBJECTS_RVA      0x6D28680u   /* GUObjectArray.ObjObjects (GUObjectArray + 0x10) */
#define BLOCK_SIZE          0x20000
#define CHUNK_ITEMS         65536
#define ITEM_SIZE           24
#define MODEL_OFF           0x50
#define MODEL_PATH_OFF      0x60

static HANDLE self_proc;
static FILE *logf;
/* this dll's folder, as UTF-16: the game may be installed in a folder with any characters */
#define PATH_CHARS 32768
static wchar_t dll_dir[PATH_CHARS];

static FILE *open_here(const wchar_t *name, const wchar_t *mode) {
    static wchar_t path[PATH_CHARS];
    _snwprintf(path, PATH_CHARS - 1, L"%ls\\%ls", dll_dir, name);
    path[PATH_CHARS - 1] = 0;
    return _wfopen(path, mode);
}

static void logm(const char *fmt, ...) {
    if (!logf) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    fprintf(logf, "%02d:%02d:%02d ", t.wHour, t.wMinute, t.wSecond);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(logf, fmt, ap);
    va_end(ap);
    fputc('\n', logf);
    fflush(logf);
}

static int rd(uintptr_t a, void *buf, size_t n) {
    SIZE_T got = 0;
    return a && ReadProcessMemory(self_proc, (LPCVOID)a, buf, n, &got) && got == n;
}
static uint64_t u64(uintptr_t a) { uint64_t v = 0; rd(a, &v, 8); return v; }
static int wr(uintptr_t a, const void *buf, size_t n) {
    SIZE_T w = 0;
    return WriteProcessMemory(self_proc, (LPVOID)a, buf, n, &w) && w == n;
}

/* ---------------- names ---------------- */
typedef struct {
    char *s;        /* full name as written in swaps.txt */
    char *base;     /* without the _N suffix */
    int blen;
    uint32_t number;
    uint64_t q;     /* FName: ComparisonIndex | Number << 32, 0 = not found */
} Name;

static Name *names;
static int nnames, cap_names;

static int add_name(const char *s) {
    for (int i = 0; i < nnames; i++)
        if (!strcmp(names[i].s, s)) return i;
    if (nnames == cap_names) {
        cap_names = cap_names ? cap_names * 2 : 1024;
        names = realloc(names, cap_names * sizeof(Name));
    }
    Name *n = &names[nnames];
    n->s = _strdup(s);
    n->base = _strdup(s);
    n->number = 0;
    n->q = 0;
    /* "Foo_12" -> base "Foo", Number 13 (no leading zero, up to 9 digits), as the engine stores it */
    char *u = strrchr(n->base, '_');
    if (u && u[1] && strlen(u + 1) <= 9 && (u[1] != '0' || !u[2])) {
        int digits = 1;
        for (char *c = u + 1; *c; c++) if (*c < '0' || *c > '9') digits = 0;
        if (digits) { n->number = (uint32_t)strtoul(u + 1, NULL, 10) + 1; *u = 0; }
    }
    n->blen = (int)strlen(n->base);
    return nnames++;
}

static uint32_t hash_ci(const char *s, int len) {
    uint32_t h = 2166136261u;
    for (int i = 0; i < len; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c >= 'A' && c <= 'Z') c += 32;
        h = (h ^ c) * 16777619u;
    }
    return h;
}

static uintptr_t blocks_slot;

static int block0_ok(uintptr_t slot) {
    unsigned char b[8];
    uint64_t b0 = u64(slot);
    return b0 && rd(b0 + 2, b, 4) && !memcmp(b, "None", 4) && u64(slot + 8);
}

/* the image (.data) holds Blocks[]: find the qword pointing at block 0 ("None", "ByteProperty") */
static uintptr_t find_blocks_slot(uintptr_t base, size_t size) {
    if (block0_ok(base + NAMEPOOL_BLOCKS_RVA)) return base + NAMEPOOL_BLOCKS_RVA;
    logm("name pool not at the known offset: searching the image...");
    size_t chunk = 1 << 20;
    uint64_t *buf = malloc(chunk);
    for (size_t off = 0; off < size; off += chunk) {
        size_t n = size - off < chunk ? size - off : chunk;
        if (!rd(base + off, buf, n)) continue;
        for (size_t i = 0; i + 1 < n / 8; i++) {
            uint64_t v = buf[i];
            if (v < 0x10000 || v > 0x7FFFFFFFFFFF || !buf[i + 1]) continue;
            unsigned char b[20];
            if (rd(v, b, 20) && !memcmp(b + 2, "None", 4) && b[7] == 0x03 && !memcmp(b + 8, "ByteProperty", 12)) {
                free(buf);
                return base + off + i * 8;
            }
        }
    }
    free(buf);
    return 0;
}

/* one pass over every name entry of the pool, matching the wanted names still unresolved
 * (case-insensitive); returns how many wanted names are resolved in total */
static int resolve_names(void) {
    int tsize = 1;
    while (tsize < nnames * 4) tsize <<= 1;
    int *table = malloc(tsize * sizeof(int));
    for (int i = 0; i < tsize; i++) table[i] = -1;
    for (int i = 0; i < nnames; i++) {
        uint32_t h = hash_ci(names[i].base, names[i].blen) & (tsize - 1);
        while (table[h] >= 0) h = (h + 1) & (tsize - 1);
        table[h] = i;
    }
    unsigned char *blk = malloc(BLOCK_SIZE);
    int found = 0;
    for (uint32_t b = 0; b < 8192; b++) {
        uint64_t p = u64(blocks_slot + 8ull * b);
        if (!p) break;
        if (!rd(p, blk, BLOCK_SIZE)) continue;
        uint32_t off = 0;
        while (off + 2 <= BLOCK_SIZE) {
            uint16_t hdr = blk[off] | (blk[off + 1] << 8);
            int len = hdr >> 6, wide = hdr & 1;
            if (!len) break;
            int bytes = wide ? len * 2 : len;
            if (off + 2 + bytes > BLOCK_SIZE) break;
            if (!wide) {
                const char *s = (const char *)blk + off + 2;
                uint32_t h = hash_ci(s, len) & (tsize - 1);
                for (; table[h] >= 0; h = (h + 1) & (tsize - 1)) {
                    Name *n = &names[table[h]];
                    if (n->blen == len && !n->q && !_strnicmp(n->base, s, len)) {
                        n->q = ((uint64_t)n->number << 32) | ((b << 16) | (off >> 1));
                        found++;
                    }
                }
            }
            off += 2 + bytes;
            off = (off + 1) & ~1u;
        }
    }
    free(blk);
    free(table);
    int total = 0;
    for (int i = 0; i < nnames; i++) total += names[i].q != 0;
    if (found || total == nnames) logm("names: %d/%d found in the name pool", total, nnames);
    return total;
}

/* ---------------- veins ----------------
 * Pulsing zombie veins = parameters of the skin materials (M_Skin / MMI_ZombieSkin). They live twice:
 *   game side   [FName][FHashedName][Assoc=2, Index=-1][value]
 *   render side [FHashedName][Index=-1, Assoc=2 + pad][value]
 * FHashedName is the same on every run, so both copies are found by hash; the value is 0x10 bytes after
 * it. Shader-map entries share the header but hold small integers: only real floats are zeroed.
 * A pass every 30 s catches materials loaded later (same work as the old tools/veins.py). */
static int veins_hide;
static const uint64_t VEIN_VECTORS[] = {0x03BE61C0DF77C9BFull};               /* Pulse Noise Speed */
static const uint64_t VEIN_SCALARS[] = {
    0xB7DD44866B3827CAull,   /* ZombieVeinBlendWeight */
    0xCEF46B663FBC6050ull,   /* Vein Intensity Min */
    0x906A15BB49C27E72ull,   /* Vein Intensity Max */
    0xD34524798F4C48C1ull,   /* Veins Normal Strength */
    0x9F5C423D240AD445ull,   /* Zombie Vein Skin Distort */
    0xD192DEB3BE6FD8F0ull,   /* Veins Blood Density */
};

static int is_float_bits(uint32_t bits) {
    bits &= 0x7FFFFFFF;
    return bits > 0x30000000 && bits < 0x47000000;
}

/* 1 = vector (4 floats), 2 = scalar, 0 = not a vein parameter */
static int vein_kind(uint64_t q) {
    if (q == VEIN_VECTORS[0]) return 1;
    for (size_t i = 0; i < sizeof VEIN_SCALARS / 8; i++)
        if (q == VEIN_SCALARS[i]) return 2;
    return 0;
}

/* Set when the game shuts down (its object tables start being freed): every thread of this dll
 * stops touching the game's memory. */
static volatile LONG stopping;

static int veins_pass(uint64_t *buf, size_t bufsize) {
    int zeroed = 0;
    MEMORY_BASIC_INFORMATION mbi;
    uintptr_t a = 0x10000;
    while (!stopping && a < 0x7FFFFFFF0000ull && VirtualQuery((LPCVOID)a, &mbi, sizeof mbi)) {
        uintptr_t start = (uintptr_t)mbi.BaseAddress, end = start + mbi.RegionSize;
        if (mbi.State == MEM_COMMIT && mbi.Type == MEM_PRIVATE && mbi.Protect == PAGE_READWRITE) {
            for (uintptr_t p = start; p < end && !stopping; p += bufsize - 64) {
                size_t n = end - p < bufsize ? end - p : bufsize;
                if (n < 64 || !rd(p, buf, n)) continue;
                size_t cnt = n / 8;
                for (size_t i = 0; i + 4 <= cnt; i++) {
                    int kind = vein_kind(buf[i]);
                    if (!kind) continue;
                    uint64_t hdr = buf[i + 1];
                    int game = hdr == 0xFFFFFFFF00000002ull;
                    int render = (uint32_t)hdr == 0xFFFFFFFFu && ((hdr >> 32) & 0xFF) == 2;
                    if (!game && !render) continue;
                    uint32_t comps[4];
                    memcpy(comps, &buf[i + 2], 16);
                    int ncomp = kind == 1 ? 4 : 1, any = 0, ok = 1;
                    for (int k = 0; k < ncomp; k++) {
                        if (comps[k]) any = 1;
                        if (comps[k] && !is_float_bits(comps[k])) ok = 0;
                    }
                    if (!any || !ok) continue;
                    static const uint32_t zero[4] = {0, 0, 0, 0};
                    zeroed += wr(p + (i + 2) * 8, zero, ncomp * 4);
                }
                Sleep(0);   /* let the game threads run between windows */
            }
        }
        a = end;
    }
    return zeroed;
}

/* Set by the object watcher when new MaterialInstanceDynamic objects appear (a zombie gets its skin
 * materials): the veins thread then runs a pass soon, instead of waiting for the periodic one. */
static volatile LONG veins_request;
#define VEINS_MIN_GAP_MS   3000    /* at most one requested pass every 3 s */
#define VEINS_SETTLE_MS     600    /* let the new materials get their parameters first */
#define VEINS_PERIOD_MS   30000    /* safety net for anything the requests miss */

static DWORD WINAPI veins_worker(LPVOID arg) {
    (void)arg;
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL);
    size_t bufsize = 4 << 20;
    uint64_t *buf = malloc(bufsize);
    DWORD last = 0;
    int first = 1;
    while (!stopping) {
        DWORD now = GetTickCount();
        LONG req = veins_request;
        int due = first || now - last >= VEINS_PERIOD_MS
                  || (req && now - (DWORD)req >= VEINS_SETTLE_MS && now - last >= VEINS_MIN_GAP_MS);
        if (due) {
            if (req) InterlockedCompareExchange(&veins_request, 0, req);
            int n = veins_pass(buf, bufsize);
            DWORD took = GetTickCount() - now;
            if (n || first) logm("veins: %d values zeroed (%lu ms)%s", n, (unsigned long)took, req ? " [new materials]" : "");
            last = GetTickCount();
            first = 0;
        }
        Sleep(200);
    }
    free(buf);
    return 0;
}

/* ---------------- swaps ---------------- */
typedef struct { int variant, mesh, target; } Swap;
static Swap *swaps;
static int nswaps, base_count;
static int *swap_table, swap_tsize;   /* variant FName -> swap index */

static int swap_of(uint64_t q) {
    uint32_t h = (uint32_t)((q * 0x9E3779B97F4A7C15ull) >> 40) & (swap_tsize - 1);
    for (; swap_table[h] >= 0; h = (h + 1) & (swap_tsize - 1))
        if (names[swaps[swap_table[h]].variant].q == q) return swap_table[h];
    return -1;
}

static int load_swaps(void) {
    FILE *f = open_here(L"swaps.txt", L"r");
    if (!f) { logm("no swaps.txt: nothing to do"); return 0; }
    char line[1024];
    int cap = 0;
    while (fgets(line, sizeof line, f)) {
        line[strcspn(line, "\r\n")] = 0;
        if (!strncmp(line, "base ", 5)) { base_count = atoi(line + 5); continue; }
        if (!strncmp(line, "veins ", 6)) { veins_hide = !strcmp(line + 6, "hide"); continue; }
        char *a = strtok(line, "|"), *b = strtok(NULL, "|"), *c = strtok(NULL, "|");
        if (!a || !b || !c) continue;
        if (nswaps == cap) { cap = cap ? cap * 2 : 1024; swaps = realloc(swaps, cap * sizeof(Swap)); }
        swaps[nswaps].variant = add_name(a);
        swaps[nswaps].mesh = add_name(b);
        swaps[nswaps].target = add_name(c);
        nswaps++;
    }
    fclose(f);
    logm("swaps.txt: %d variants (%d Walker/Shambler), veins %s", nswaps, base_count, veins_hide ? "hidden" : "unchanged");
    return 1;
}

static void index_swaps(void) {
    swap_tsize = 1;
    while (swap_tsize < nswaps * 4) swap_tsize <<= 1;
    swap_table = malloc(swap_tsize * sizeof(int));
    for (int i = 0; i < swap_tsize; i++) swap_table[i] = -1;
    int usable = 0;
    for (int i = 0; i < nswaps; i++) {
        Swap *s = &swaps[i];
        if (!names[s->variant].q || !names[s->mesh].q || !names[s->target].q) continue;
        if (names[s->mesh].q == names[s->target].q) continue;
        uint64_t q = names[s->variant].q;
        uint32_t h = (uint32_t)((q * 0x9E3779B97F4A7C15ull) >> 40) & (swap_tsize - 1);
        while (swap_table[h] >= 0) h = (h + 1) & (swap_tsize - 1);
        swap_table[h] = i;
        usable++;
    }
    logm("swaps usable: %d", usable);
    if (base_count > usable) base_count = usable;
    nswaps = usable ? nswaps : 0;
}

/* ---------------- bundles ---------------- */
static uint64_t Q_TYPE, Q_BUNDLE;

/* bundle entry in the AssetManager tables: [type][variant][CharacterMesh][TArray data][num|max] */
static int patch_bundles(void) {
    static uint64_t buf[1 << 20];   /* 8 MB window */
    int found = 0, rewritten = 0;
    char *seen = calloc(nswaps, 1);
    MEMORY_BASIC_INFORMATION mbi;
    uintptr_t a = 0x10000;
    while (a < 0x7FFFFFFF0000ull && VirtualQuery((LPCVOID)a, &mbi, sizeof mbi)) {
        uintptr_t start = (uintptr_t)mbi.BaseAddress, end = start + mbi.RegionSize;
        if (mbi.State == MEM_COMMIT && mbi.Type == MEM_PRIVATE && mbi.Protect == PAGE_READWRITE) {
            for (uintptr_t p = start; p < end; p += sizeof buf - 64) {
                size_t n = end - p < sizeof buf ? end - p : sizeof buf;
                if (n < 64 || !rd(p, buf, n)) continue;
                size_t cnt = n / 8;
                for (size_t i = 0; i + 5 <= cnt; i++) {
                    if (buf[i] != Q_TYPE || buf[i + 2] != Q_BUNDLE) continue;
                    int s = swap_of(buf[i + 1]);
                    if (s < 0) continue;
                    uint64_t ptr = buf[i + 3];
                    uint32_t num = (uint32_t)buf[i + 4];
                    if (!ptr || !num || num >= 16) continue;
                    if (!seen[s]) { seen[s] = 1; found++; }
                    for (uint32_t k = 0; k < num; k++)
                        if (u64(ptr + 24ull * k) == names[swaps[s].mesh].q)
                            rewritten += wr(ptr + 24ull * k, &names[swaps[s].target].q, 8);
                }
            }
        }
        a = end;
    }
    free(seen);
    logm("bundles: %d/%d found, %d mesh paths rewritten", found, nswaps, rewritten);
    return found;
}

/* ---------------- objects ---------------- */
static uintptr_t objobjects;

static int objarray_ok(uintptr_t oo) {
    uint32_t v[4];
    return u64(oo) && rd(oo + 0x10, v, 16) && v[1] > 100000 && v[1] <= v[0] && v[0] < (1u << 26)
           && v[2] == (v[0] + CHUNK_ITEMS - 1) / CHUNK_ITEMS && v[3] == (v[1] + CHUNK_ITEMS - 1) / CHUNK_ITEMS;
}

/* the known offset holds a chunked object array (it may still be filling up at startup) */
static int objarray_shape_ok(uintptr_t oo) {
    uint32_t v[4];
    return u64(oo) && rd(oo + 0x10, v, 16) && v[0] >= CHUNK_ITEMS && v[0] < (1u << 26) && v[1] <= v[0]
           && v[2] == (v[0] + CHUNK_ITEMS - 1) / CHUNK_ITEMS;
}

static uintptr_t find_objobjects(uintptr_t base, size_t size) {
    if (objarray_shape_ok(base + OBJOBJECTS_RVA)) return base + OBJOBJECTS_RVA;
    logm("object array not at the known offset: searching the image...");
    for (size_t off = 0; off + 0x20 < size; off += 8)
        if (objarray_ok(base + off)) return base + off;
    return 0;
}

static int committed(uintptr_t a) {
    MEMORY_BASIC_INFORMATION mbi;
    return VirtualQuery((LPCVOID)a, &mbi, sizeof mbi) && mbi.State == MEM_COMMIT
           && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD));
}

static uint64_t name_of(uintptr_t ob) { return u64(ob + 0x18); }
static uintptr_t class_of(uintptr_t ob) { return u64(ob + 0x10); }

static uintptr_t find_class(uint64_t q_name, uint64_t q_class) {
    uintptr_t chunks = u64(objobjects);
    uint32_t num = 0;
    rd(objobjects + 0x14, &num, 4);
    for (uint32_t i = 0; i < num; i++) {
        uintptr_t chunk = u64(chunks + 8ull * (i / CHUNK_ITEMS));
        uintptr_t ob = chunk ? u64(chunk + (uintptr_t)(i % CHUNK_ITEMS) * ITEM_SIZE) : 0;
        if (ob && name_of(ob) == q_name && name_of(class_of(ob)) == q_class) return ob;
    }
    return 0;
}

typedef struct { uint32_t idx; uintptr_t ob; int swap; } Tracked;

static DWORD WINAPI worker(LPVOID arg) {
    (void)arg;
    self_proc = GetCurrentProcess();
    logf = open_here(L"di2swap.log", L"w");
    logm("di2swap started");
    if (!load_swaps()) return 0;
    if (!nswaps && !veins_hide) { logm("nothing to do"); return 0; }

    uintptr_t base = (uintptr_t)GetModuleHandleW(NULL);
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    size_t size = nt->OptionalHeader.SizeOfImage;

    /* the pool and the object array exist early, but wait for the menu's AssetManager tables */
    for (int tries = 0; !(blocks_slot = find_blocks_slot(base, size)) || !(objobjects = find_objobjects(base, size)); tries++) {
        if (tries > 60) { logm("game structures not found: giving up"); return 0; }
        Sleep(1000);
    }
    logm("name pool slot +0x%llx, object array +0x%llx", (unsigned long long)(blocks_slot - base),
         (unsigned long long)(objobjects - base));
    int q_type = add_name("ModelVariantAsset"), q_bundle = add_name("CharacterMesh"), q_class = add_name("Class");
    int q_mid = add_name("MaterialInstanceDynamic");
    /* the game registers most asset names a few seconds after it starts (asset registry, AssetManager):
     * started early, we would find only half of them. Resolve again every 2 s until all are found or
     * the count stops growing for 10 s (up to 3 minutes). */
    for (int tries = 0, last = -1, stable = 0; tries < 90; tries++) {
        int found = resolve_names();
        if (found == nnames) break;
        stable = found == last ? stable + 1 : 0;
        if (stable >= 5) break;
        last = found;
        Sleep(2000);
    }
    Q_TYPE = names[q_type].q;
    Q_BUNDLE = names[q_bundle].q;
    if (nswaps) {
        index_swaps();
        if (!Q_TYPE || !Q_BUNDLE) nswaps = 0;
    }
    if (nswaps) {
        int last = -1;
        for (int tries = 0; tries < 200; tries++) {
            int n = patch_bundles();
            if (n == nswaps || (n >= base_count && n == last && n > 0)) break;
            last = n;
            Sleep(3000);
        }
    }
    logm("ready");

    /* class objects (named X, their class named "Class"): variants to swap, materials for the veins */
    uintptr_t cls = nswaps ? find_class(Q_TYPE, names[q_class].q) : 0;
    uintptr_t mid_cls = veins_hide ? find_class(names[q_mid].q, names[q_class].q) : 0;
    if (nswaps && !cls) { logm("ModelVariantAsset class not found: no model swap"); nswaps = 0; }
    if (veins_hide) {
        if (!mid_cls) logm("MaterialInstanceDynamic class not found: veins every 30 s only");
        HANDLE t = CreateThread(NULL, 0, veins_worker, NULL, 0, NULL);
        if (t) CloseHandle(t);
    }
    if (!nswaps && !mid_cls) { logm("watcher not needed"); return 0; }

    /* watcher: every 2 ms compare the object slots with the previous pass */
    timeBeginPeriod(1);
    uint32_t cap = 0;
    uint64_t *prev = NULL;
    Tracked *tracked = NULL;
    int ntracked = 0, cap_tracked = 0, first_pass = 1;
    unsigned long long patched = 0;
    while (!stopping) {
        uintptr_t chunks = u64(objobjects);
        uint32_t num = 0;
        rd(objobjects + 0x14, &num, 4);
        if (!chunks || !num) { InterlockedExchange(&stopping, 1); break; }   /* game shutting down */
        if (num > cap) {
            prev = realloc(prev, (size_t)num * 8);
            memset(prev + cap, 0, (size_t)(num - cap) * 8);
            cap = num;
        }
        for (uint32_t c = 0; c * CHUNK_ITEMS < num; c++) {
            uintptr_t chunk = u64(chunks + 8ull * c);
            if (!chunk) continue;
            uint32_t n = num - c * CHUNK_ITEMS;
            if (n > CHUNK_ITEMS) n = CHUNK_ITEMS;
            /* the chunk tables live as long as the game; when it shuts down they are freed: read them
             * directly (fast) only while both ends are still committed memory, else stop for good */
            if (!committed(chunk) || !committed(chunk + (size_t)n * ITEM_SIZE - 8)) {
                InterlockedExchange(&stopping, 1);
                break;
            }
            const uint8_t *items = (const uint8_t *)chunk;
            for (uint32_t j = 0; j < n; j++) {
                uint32_t idx = c * CHUNK_ITEMS + j;
                uint64_t ob = *(const volatile uint64_t *)(items + (size_t)j * ITEM_SIZE);
                if (ob == prev[idx]) continue;
                prev[idx] = ob;
                for (int t = 0; t < ntracked; t++)
                    if (tracked[t].idx == idx) { tracked[t] = tracked[--ntracked]; break; }
                if (!ob) continue;
                uintptr_t oc = class_of(ob);
                if (mid_cls && oc == mid_cls && !first_pass)
                    InterlockedExchange(&veins_request, (LONG)(GetTickCount() | 1));
                if (!nswaps || oc != cls) continue;
                int s = swap_of(name_of(ob));
                if (s < 0) continue;
                if (ntracked == cap_tracked) {
                    cap_tracked = cap_tracked ? cap_tracked * 2 : 256;
                    tracked = realloc(tracked, cap_tracked * sizeof(Tracked));
                }
                tracked[ntracked++] = (Tracked){idx, ob, s};
            }
        }
        if (stopping) break;   /* never write once the game is going away */
        /* variants are tracked from the moment they exist until their Model holds the old mesh */
        for (int t = 0; t < ntracked; t++) {
            Swap *s = &swaps[tracked[t].swap];
            if (u64(tracked[t].ob + MODEL_PATH_OFF) == names[s->mesh].q) {
                int32_t weak[4] = {-1, 0, 0, 0};   /* cached weak pointer -> none, tag 0 */
                wr(tracked[t].ob + MODEL_OFF, weak, sizeof weak);
                wr(tracked[t].ob + MODEL_PATH_OFF, &names[s->target].q, 8);
                if (++patched <= 50 || patched % 100 == 0)
                    logm("%s: model (%llu)", names[s->variant].s, patched);
            }
        }
        first_pass = 0;
        Sleep(2);
    }
    logm("game shutting down: stopped");
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(h);
        GetModuleFileNameW(h, dll_dir, PATH_CHARS);
        wchar_t *slash = wcsrchr(dll_dir, L'\\');
        if (slash) *slash = 0;
        HANDLE t = CreateThread(NULL, 0, worker, NULL, 0, NULL);
        if (t) CloseHandle(t);
    } else if (reason == DLL_PROCESS_DETACH) {
        InterlockedExchange(&stopping, 1);
    }
    return TRUE;
}
