# Software Requirements Specification (SRS) — LocalVault

| Atribut | Nilai |
|---|---|
| Dokumen | Software Requirements Specification |
| Produk | LocalVault |
| Versi produk | 1.0 |
| Versi dokumen | 1.0 |
| Status | Baseline implementasi |
| Tanggal | 20 Juli 2026 |
| Bahasa normatif | Indonesia |

## 1. Pendahuluan

### 1.1 Tujuan

Dokumen ini menetapkan persyaratan produk, perilaku, data, antarmuka, keamanan, pengemasan, pengujian, dan kriteria penerimaan LocalVault. Dokumen ini bergaya IEEE dan bersifat normatif: implementer, termasuk implementer AI, harus dapat membangun v1 tanpa keputusan produk yang belum ditentukan.

Kata **HARUS**, **TIDAK BOLEH**, **SEBAIKNYA**, dan **BOLEH** menunjukkan tingkat kewajiban. Jika contoh bertentangan dengan persyaratan ber-ID, persyaratan ber-ID yang berlaku.

### 1.2 Ruang lingkup produk

LocalVault adalah password manager lokal dengan akun pengguna dan satu vault per pengguna. Satu proses host menyimpan envelope vault terenkripsi di PostgreSQL dan melayani banyak tab atau perangkat klien pada LAN melalui aplikasi web. Produk didistribusikan sebagai aplikasi host portable untuk Windows, macOS, dan Linux; PostgreSQL harus tersedia pada deployment host.

Nilai utama produk adalah:

- menyimpan kredensial secara terenkripsi di host milik pengguna;
- menyediakan pengelolaan, pencarian, impor, ekspor, Trash, dan backup dari browser modern;
- menyinkronkan perubahan antarklien LAN secara langsung;
- dapat dipindahkan atau ditingkatkan dengan mempertahankan folder data di samping launcher.

### 1.3 Audiens

Dokumen ini ditujukan bagi pengembang backend, frontend, launcher/tray, keamanan, quality assurance, release engineering, dan pemilik produk.

### 1.4 Istilah dan singkatan

| Istilah | Definisi |
|---|---|
| AAD | *Additional Authenticated Data* yang diautentikasi tetapi tidak dienkripsi oleh AEAD. |
| AEAD | Enkripsi yang memberi kerahasiaan dan autentikasi, dalam produk ini AES-256-GCM. |
| CSPRNG | Generator angka acak yang aman secara kriptografis dari sistem operasi. |
| DEK | *Data Encryption Key*, kunci acak 256-bit untuk mengenkripsi payload vault. |
| KEK | *Key Encryption Key*, kunci 256-bit untuk membungkus DEK. |
| LAN | Jaringan lokal yang dapat mencapai alamat dan port host. |
| Launcher | Executable native portable yang mengelola server dan menu tray. |
| Mutasi | Operasi yang mengubah vault atau pengaturan yang disimpan. |
| Payload vault | Dokumen JSON kanonik yang berisi seluruh data rahasia aplikasi. |
| Revision | Bilangan bulat monoton untuk optimistic concurrency. |
| Sesi | Otorisasi in-memory yang dimiliki tepat oleh satu tab browser. |
| Snapshot | Backup terenkripsi pada titik waktu tertentu. |
| Vault | Satu kumpulan data LocalVault beserta envelope kriptografinya. |

### 1.5 Referensi normatif dan informatif

1. [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) — Argon2id dan penyimpanan password.
2. [OWASP Cryptographic Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html) — authenticated encryption, pengelolaan kunci, dan CSPRNG.
3. [MDN Secure Contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts) — batas secure context pada origin HTTP.
4. [MDN Clipboard API](https://developer.mozilla.org/en-US/docs/Web/API/Clipboard_API) — batas akses clipboard browser.
5. [Google Chrome — Import or export passwords with Chrome](https://support.google.com/chrome/answer/13068232) — interoperabilitas CSV Chromium.
6. [Mozilla Firefox — Export login data from Firefox](https://support.mozilla.org/en-US/kb/export-login-data-firefox) — interoperabilitas CSV Firefox dan sifat plaintext hasil ekspor.
7. [PyInstaller — Using PyInstaller](https://pyinstaller.org/en/stable/usage.html) — bundling mandiri dan build terpisah pada setiap OS.
8. [WCAG 2.2](https://www.w3.org/TR/WCAG22/) — target aksesibilitas AA.

### 1.6 Konvensi identitas persyaratan

| Awalan | Area |
|---|---|
| PRD | produk dan deployment |
| SET | first-run setup |
| SES | autentikasi dan sesi |
| CRD | kredensial, kategori, dan tag |
| GEN | generator password |
| TRS | Trash dan operasi massal |
| IMP | impor |
| EXP | ekspor |
| BAK | backup, restore, dan migrasi |
| SEC | keamanan dan kriptografi |
| DAT | model dan persistensi data |
| API | REST dan WebSocket |
| UIX | antarmuka dan pengalaman pengguna |
| I18N | internasionalisasi |
| OPS | launcher, operasi, dan log |
| QUA | kualitas, kompatibilitas, dan performa |

Semua persyaratan v1 pada dokumen ini berprioritas **Must** kecuali dinyatakan lain.

## 2. Deskripsi keseluruhan

### 2.1 Konteks dan batas sistem

```text
┌──────────────────────────────────────────────────────────┐
│ Host portable                                            │
│ ┌─────────────┐  lifecycle  ┌──────────────────────────┐ │
│ │ Tray/       │─────────────▶│ FastAPI + static React  │ │
│ │ Launcher    │              │ REST JSON + WebSocket   │ │
│ └─────────────┘              └──────────┬───────────────┘ │
│                                        │                 │
│                             encrypted envelope only      │
│                                        ▼                 │
│              PostgreSQL + LocalVault-Data/{backup,config,log} │
└───────────────────────────────┬──────────────────────────┘
                                │ HTTP/WS pada LAN
                 ┌──────────────┼──────────────┐
                 ▼              ▼              ▼
              Desktop         Tablet         Ponsel
              browser         browser         browser
```

Browser hanya berkomunikasi dengan origin LocalVault. Tidak ada font, script, style, analytics, favicon, pemeriksaan kebocoran, update, atau aset lain yang diambil dari internet. Membuka URL kredensial adalah navigasi browser yang hanya terjadi setelah tindakan eksplisit pengguna dan bukan fetch oleh server.

### 2.2 Profil pengguna

Produk memiliki tepat satu identitas pemilik berbasis master password dan tidak memiliki akun, role, izin per-item, atau sharing. Pemilik diasumsikan mampu menjalankan aplikasi portable, membuka alamat LAN, dan memahami peringatan bahwa CSV hasil ekspor tidak terenkripsi.

### 2.3 Lingkungan operasi

- Host: Windows, macOS, atau distribusi Linux desktop 64-bit yang tercantum dalam release matrix.
- Klien: dua rilis stabil terbaru Google Chrome, Microsoft Edge, dan Mozilla Firefox pada tanggal rilis; Safari stabil terbaru pada tanggal rilis.
- Lebar viewport minimum yang didukung: 360 CSS px.
- Jaringan: loopback atau IPv4 LAN yang dapat merutekan TCP ke host.
- Protokol v1: HTTP dan WebSocket tanpa TLS.

### 2.4 Keputusan produk yang diterima

| Keputusan | Konsekuensi wajib |
|---|---|
| HTTP tanpa TLS pada LAN | Konten, master password saat unlock, token, dan secret yang dilihat dapat disadap atau diubah pihak LAN. Banner bahaya harus selalu terlihat. |
| Setup oleh klien LAN pertama tanpa bootstrap code | Host baru yang terekspos dapat diambil alih klien LAN lain sebelum pemilik menyelesaikan setup. |
| Master password hanya wajib tidak kosong | Password lemah diizinkan setelah peringatan eksplisit. |
| Tidak ada throttling atau lockout | Brute force online tidak dicegah aplikasi. |
| Tidak ada idle timeout | Sesi tetap aktif selama tab mempertahankan kepemilikan sesi. |
| Tidak ada clipboard auto-clear | Secret yang disalin tetap berada di clipboard sampai ditimpa pengguna atau sistem. |

### 2.5 Asumsi dan dependensi

- Host, OS, runtime browser, dan akun OS pengguna dianggap tidak terkompromi.
- CSPRNG, AES-GCM, Argon2id, dan implementasi kriptografi yang digunakan berasal dari library terpelihara; algoritme kriptografi tidak boleh diimplementasikan sendiri.
- `crypto.subtle` dan Clipboard API modern tidak diasumsikan tersedia pada alamat HTTP LAN. Kriptografi utama dilakukan di server dan copy memiliki fallback.
- Build release dibuat serta diuji pada masing-masing OS target; build satu OS tidak dianggap artefak lintas platform.

### 2.6 Di luar cakupan v1

Multi-user, role, sharing, cloud sync, browser extension, autofill, HTTPS, TOTP, passkey, secure note sebagai tipe item terpisah, kartu, identitas, attachment, impor XLSX langsung, audit kesehatan password, breach lookup, clipboard auto-clear, idle timeout, rate limiting, bootstrap protection, telemetry, CDN, favicon online, auto-update, dan pengambilan metadata URL berada di luar cakupan.

## 3. Persyaratan produk dan deployment

| ID | Persyaratan |
|---|---|
| PRD-001 | Backend HARUS menggunakan Python dan FastAPI; penyimpanan HARUS menggunakan PostgreSQL melalui asyncpg; frontend HARUS menggunakan React dan TypeScript; antarmuka aplikasi HARUS REST JSON dan WebSocket. |
| PRD-002 | Build frontend teroptimasi HARUS dibundel sebagai aset backend dan dilayani dari origin serta port yang sama. |
| PRD-003 | Tidak boleh ada ketergantungan runtime pada CDN, koneksi internet, instalasi Python, instalasi Node.js, atau package manager. PostgreSQL adalah dependency runtime resmi dan dikonfigurasi melalui `DATABASE_URL`. |
| PRD-004 | Release HARUS menghasilkan artefak portable terpisah untuk Windows, macOS, dan Linux dari runner OS yang sama dengan target. |
| PRD-005 | Launcher HARUS menjalankan satu instance server, menampilkan tray menu, membuka browser default, dan menghentikan server secara tertib. |
| PRD-006 | Server HARUS bind pada `0.0.0.0` menggunakan HTTP IPv4 dengan port persisten. Port awal v1 HARUS `8741`, disimpan di `config.json`, dan tidak boleh berpindah otomatis jika port sedang dipakai. |
| PRD-007 | Kegagalan bind HARUS menghentikan startup, menampilkan pesan yang menyebut port, dan menawarkan aksi membuka lokasi log; aplikasi TIDAK BOLEH memilih port acak. |
| PRD-008 | Data HARUS berada dalam direktori `LocalVault-Data` di samping launcher, bukan di profile global OS. |
| PRD-009 | Startup HARUS ditolak sebelum server bind jika direktori data atau subdirektori wajib tidak dapat dibuat, dibaca, dan ditulis. Tes writability HARUS membuat, flush, rename atomik, lalu menghapus file probe tanpa menyentuh vault. |
| PRD-010 | Mengganti artefak aplikasi untuk upgrade TIDAK BOLEH menghapus, memindahkan, atau menimpa `LocalVault-Data`. |
| PRD-011 | Hanya satu proses LocalVault BOLEH membuka satu direktori data. Instance kedua HARUS berhenti dengan pesan bahwa aplikasi sudah berjalan. |
| PRD-012 | UI HARUS dapat diakses melalui `http://127.0.0.1:8741` dan setiap alamat IPv4 LAN aktif host pada port terkonfigurasi. |
| PRD-013 | Data directory HARUS berada pada filesystem yang mendukung exclusive file lock, flush durability, dan atomic rename dalam direktori yang sama. Startup self-test HARUS menolak lokasi yang tidak menyediakan semantik tersebut; network share yang tidak dapat membuktikannya tidak didukung. |

Struktur direktori normatif:

```text
<folder-portable>/
├── LocalVault[.exe atau launcher platform]
└── LocalVault-Data/
    ├── config.json
    ├── backups/
    ├── logs/
    └── localvault.lock
```

`localvault.lock` adalah lock runtime dan boleh tersisa setelah crash; kepemilikan harus diverifikasi melalui OS lock, bukan keberadaan file saja.

## 4. Persyaratan fungsional

### 4.1 Setup pertama

| ID | Persyaratan |
|---|---|
| SET-001 | `GET /api/v1/status` HARUS dapat dipanggil tanpa sesi dan hanya mengembalikan status setup, versi aplikasi/API/schema, serta kapabilitas non-rahasia. |
| SET-002 | Saat belum pernah disiapkan, klien LAN pertama BOLEH menjalankan setup tanpa bootstrap code. |
| SET-003 | Setup HARUS menerima master password yang tidak kosong, konfirmasi yang identik, pilihan membuat recovery key, bahasa UI, dan acknowledgement risiko HTTP LAN. |
| SET-004 | Master password TIDAK BOLEH memiliki batas panjang aplikasi atau aturan komposisi; keterbatasan praktis hanya memori request dan library, dengan request setup/unlock maksimum 1 MiB. |
| SET-005 | UI HARUS menampilkan strength indicator lokal dan peringatan jika master password dinilai lemah. Pengguna BOLEH melanjutkan setelah mencentang konfirmasi peringatan. Nilai atau skor strength TIDAK BOLEH dikirim ke layanan eksternal. |
| SET-006 | Perlombaan setup HARUS diselesaikan atomik. Tepat satu request boleh membuat vault; request lain mendapat `409 SETUP_ALREADY_COMPLETED`. |
| SET-007 | Setelah setup pertama berhasil, endpoint setup HARUS tetap tertutup dan selalu merespons `409 SETUP_ALREADY_COMPLETED`, termasuk setelah reset vault. Reset membuat vault kosong baru melalui endpoint reset, bukan membuka setup kembali. |
| SET-008 | Jika dipilih, recovery key HARUS ditampilkan tepat satu kali setelah transaksi setup berhasil, tidak boleh dicatat ke log atau dapat diminta ulang. Pengguna harus mengonfirmasi telah menyimpannya sebelum meninggalkan layar. |
| SET-009 | Jika recovery dilewati, UI HARUS menyatakan bahwa kehilangan master password membuat data tidak dapat dipulihkan. |

### 4.2 Unlock, sesi, dan lock

| ID | Persyaratan |
|---|---|
| SES-001 | Unlock HARUS memverifikasi master password dengan mencoba membuka DEK dan mengautentikasi envelope; tidak boleh menyimpan verifier password terpisah yang memungkinkan jalan pintas terhadap envelope. |
| SES-002 | Unlock yang berhasil HARUS menghasilkan token sesi acak minimal 256 bit dari CSPRNG. Token hanya disimpan dalam memori server dan `sessionStorage` tab. |
| SES-003 | REST terautentikasi HARUS menerima token hanya sebagai `Authorization: Bearer <token>`. Token tidak boleh berada dalam cookie, `localStorage`, IndexedDB, URL, file, atau log. |
| SES-004 | Satu token HARUS dimiliki tepat oleh satu tab. Setiap tab baru harus unlock sendiri. Jika browser menggandakan `sessionStorage`, koneksi kepemilikan kedua harus ditolak dan salinan token di tab kedua harus dihapus. |
| SES-005 | Tab HARUS mempertahankan WebSocket kepemilikan sesi. Putus koneksi memberi grace period 10 detik; reconnect dengan token yang sama dalam periode itu mempertahankan unlock sehingga reload tab tidak mengunci. Setelah grace period, token dimusnahkan. |
| SES-006 | Menutup tab HARUS mengakhiri sesi server paling lambat 10 detik setelah WebSocket terputus. `pagehide`/`sendBeacon` BOLEH mempercepat, tetapi grace period adalah mekanisme otoritatif. |
| SES-007 | Tidak boleh ada idle timeout atau absolute session timeout selama koneksi kepemilikan aktif. |
| SES-008 | Lock manual HARUS menghapus token tab, memutus WebSocket, menghapus state rahasia frontend, dan mengakhiri sesi server. |
| SES-009 | `Lock semua sesi` dari tray atau API HARUS membatalkan seluruh token, menutup koneksi event, membersihkan cache plaintext/key secara best-effort, dan mengarahkan seluruh klien ke layar lock. |
| SES-010 | Stop/restart/crash server HARUS mengakhiri seluruh sesi karena token tidak dipersistenkan. |
| SES-011 | Banyak tab/perangkat dengan token berbeda BOLEH aktif bersamaan. Vault plaintext server BOLEH dipakai bersama selama sedikitnya satu sesi valid ada, tetapi harus dibersihkan best-effort saat sesi terakhir berakhir. |
| SES-012 | Aplikasi TIDAK BOLEH menerapkan delay, throttling, CAPTCHA, atau lockout atas kegagalan unlock. Respons gagal tidak boleh membedakan salah master password, envelope rusak, atau vault ID tidak cocok. |
| SES-013 | Reautentikasi master password HARUS diminta hanya untuk ekspor plaintext dan reset vault. Pergantian master password secara inheren memerlukan master lama; aksi kritis lain cukup dengan sesi unlocked. |

Memasukkan master/recovery historis untuk membuka backup yang tidak dapat dibuka oleh DEK sesi aktif adalah input dekripsi kandidat, bukan reautentikasi atas vault aktif, dan hanya boleh diminta pada kondisi BAK-008.

### 4.3 Kredensial, kategori, tag, dan custom field

| ID | Persyaratan |
|---|---|
| CRD-001 | Tampilan utama HARUS berupa tabel kredensial dengan panel detail yang dapat dibuka tanpa reload halaman. |
| CRD-002 | Credential HARUS memiliki: UUID, nama wajib, URL opsional, username/email opsional, password, satu kategori opsional, nol atau lebih tag, favorit, catatan, timestamp UTC, revision, dan nol atau lebih custom field. |
| CRD-003 | Nama setelah trim HARUS memiliki 1–300 karakter Unicode. URL, username, dan password BOLEH kosong. Catatan maksimum 100.000 karakter. Batas gabungan payload satu Credential adalah 1 MiB UTF-8. |
| CRD-004 | Setiap custom field HARUS memiliki UUID, label 1–100 karakter, tipe `text` atau `secret`, nilai maksimum 100.000 karakter, dan urutan bilangan bulat. Label harus unik secara Unicode-NFKC-casefold dalam satu Credential. |
| CRD-005 | Password dan custom field `secret` HARUS masked saat pertama dirender. State reveal diindeks per entity/field dalam memori tab dan tetap terbuka saat panel ditutup/dibuka kembali sampai pengguna menyembunyikannya atau sesi berakhir; state tidak boleh dipersistenkan. |
| CRD-006 | Copy HARUS tersedia untuk password, username, URL, serta semua custom field. Aplikasi TIDAK BOLEH membersihkan clipboard otomatis. |
| CRD-007 | Copy pertama-tama HARUS mencoba Clipboard API jika tersedia. Jika diblokir, UI HARUS mencoba fallback seleksi/`execCommand('copy')`; jika masih gagal, tampilkan dialog manual-copy dengan teks terseleksi dan peringatan agar pengguna menyalin sendiri. |
| CRD-008 | Membuat, memperbarui, memindah ke Trash, restore, dan purge HARUS menaikkan revision Credential dan revision vault secara monoton. |
| CRD-009 | Update dan delete HARUS memakai optimistic concurrency. Stale edit mendapat `409 REVISION_CONFLICT`, revision terbaru, dan pilihan UI `Muat ulang` atau `Timpa perubahan saya`. |
| CRD-010 | Overwrite konflik HARUS eksplisit: klien mengambil item terbaru, mengirim ulang nilai edit dengan `base_revision` lama, `If-Match` revision terbaru, dan `conflict_resolution: "overwrite"`. Tindakan harus dicatat tanpa nilai rahasia. |
| CRD-011 | Saat password berubah ke nilai yang berbeda, password sebelumnya dan timestamp perubahan HARUS dimasukkan ke history terenkripsi; hanya lima history terbaru dipertahankan. Update field lain tidak menambah history. |
| CRD-012 | History HARUS dapat dilihat dan disalin dari panel detail, masked secara default, dan tidak boleh diubah terpisah. |
| CRD-013 | Satu Credential BOLEH memiliki paling banyak satu Category dan banyak tag unik. Perbandingan nama category/tag untuk keunikan menggunakan Unicode NFKC + casefold, sedangkan casing tampilan pertama dipertahankan. |
| CRD-014 | Category HARUS dapat dibuat, diganti nama, dan dihapus. Menghapus Category membuat `category_id` Credential terkait menjadi `null`, tanpa menghapus Credential. |
| CRD-015 | Tag berasal dari katalog terenkripsi dalam payload dan HARUS dapat dibuat, diganti nama secara global, digabungkan bila nama tujuan sudah ada, serta dihapus dari semua Credential. |
| CRD-016 | Favorit HARUS dapat diubah per item atau secara massal. |
| CRD-017 | Pencarian HARUS mencocokkan nama, URL, username, kategori, tag, catatan, label custom field, dan nilai custom field `text`; pencarian default TIDAK BOLEH mencocokkan password, history, atau nilai custom field `secret`. |
| CRD-018 | Pencarian dan filter HARUS berjalan instan pada data plaintext yang sudah sah berada di memori sesi/server; implementasi TIDAK BOLEH membuat indeks plaintext persisten. |
| CRD-019 | Filter HARUS mendukung category, tag gabungan AND/OR, favorit, status aktif/Trash, dan keberadaan URL/username. |
| CRD-020 | Sorting HARUS mendukung nama, waktu dibuat, waktu diubah, category, dan favorit, masing-masing naik/turun. Tie-breaker wajib adalah UUID naik agar hasil stabil. |

### 4.4 Generator password

| ID | Persyaratan |
|---|---|
| GEN-001 | Password HARUS dibuat server-side menggunakan CSPRNG OS dan sampling tanpa modulo bias. |
| GEN-002 | Default generator HARUS panjang 20 dengan huruf kecil, huruf besar, angka, dan simbol aktif serta karakter ambigu disertakan. |
| GEN-003 | Pengguna HARUS dapat memilih panjang 4–256, masing-masing charset, dan opsi mengecualikan set karakter ambigu dengan code point `U+0049 U+006C U+0031 U+004F U+0030 U+006F U+007C U+005C U+0060 U+0027 U+0022`. Sedikitnya satu charset harus aktif. |
| GEN-004 | Bila panjang mencukupi, hasil HARUS mengandung setidaknya satu karakter dari setiap charset yang dipilih lalu diacak ulang secara aman. |
| GEN-005 | Hasil generator TIDAK BOLEH masuk log, backup, history, atau payload sampai pengguna menyimpan Credential. Respons generator harus `Cache-Control: no-store`. |

### 4.5 Trash dan aksi massal

| ID | Persyaratan |
|---|---|
| TRS-001 | Delete normal HARUS berupa soft delete ke Trash dengan `deleted_at` UTC; item Trash tidak muncul pada daftar aktif. |
| TRS-002 | Item Trash HARUS dapat direstore dengan data dan history utuh. Restore menghapus `deleted_at`. |
| TRS-003 | Server HARUS purge item ketika `now_utc >= deleted_at + 30 hari`, pada startup dan sekali setiap 24 jam selama proses berjalan. |
| TRS-004 | Pengguna HARUS dapat mengosongkan Trash manual setelah dialog konfirmasi yang menyebut jumlah item. |
| TRS-005 | Aksi massal HARUS mencakup tambah/hapus tag, ubah category, set/unset favorit, pindah ke Trash, restore, dan purge permanen. |
| TRS-006 | Setiap operasi massal HARUS atomik. Jika satu item hilang atau stale, tidak ada item berubah dan respons memuat daftar ID/revision yang konflik tanpa secret. |
| TRS-007 | Sebelum bulk destructive action—pindah ke Trash, purge, empty Trash, atau penghapusan category/tag yang memengaruhi banyak item—server HARUS membuat snapshot pre-operation yang tervalidasi. Jika snapshot gagal, operasi dibatalkan. |

## 5. Impor dan ekspor

### 5.1 Impor CSV

| ID | Persyaratan |
|---|---|
| IMP-001 | Importer generik HARUS menerima CSV UTF-8 dengan atau tanpa BOM dan mendeteksi delimiter koma, titik koma, atau tab. Encoding lain ditolak dengan error yang dapat ditindaklanjuti. |
| IMP-002 | Parser HARUS mendukung quoted field, escaped quote, CRLF/LF, dan newline di dalam quoted field sesuai RFC 4180 untuk delimiter yang dipilih. Maksimum upload adalah 50 MiB dan 100.000 baris. |
| IMP-003 | Alur impor HARUS dua tahap: preview lalu commit. Preview tidak boleh memutasi vault. |
| IMP-004 | UI mapping HARUS memetakan kolom ke name, URL, username, password, category, tags, favorite, notes, created_at, updated_at, `custom_fields_json`, atau custom field baru/yang ada dengan tipe `text`/`secret`; kolom BOLEH diabaikan. Timestamp sumber hanya dipakai bila valid dan tidak berada di masa depan, selainnya server memakai waktu commit. |
| IMP-005 | Preview HARUS menampilkan sampel 100 baris pertama, jumlah valid/invalid, hasil mapping, konflik, dan error bernomor baris. |
| IMP-006 | Baris valid BOLEH di-commit walaupun baris lain invalid. Pengguna harus mengonfirmasi jumlah yang akan diimpor. |
| IMP-007 | Laporan error HARUS dapat diunduh sebagai CSV UTF-8 BOM berisi `row_number,error_code,message` dan TIDAK BOLEH menyertakan nilai sumber. |
| IMP-008 | Preset `chromium` HARUS mengimpor header `name,url,username,password,note`; nama `note` dipetakan ke notes. Header tambahan diabaikan tetapi dicatat sebagai warning. |
| IMP-009 | Preset `firefox` HARUS mengimpor `url,username,password,httpRealm,formActionOrigin,guid,timeCreated,timeLastUsed,timePasswordChanged`; `url`, `username`, dan `password` adalah field utama, kolom lain boleh dipakai untuk timestamp bila valid dan selainnya diabaikan dengan warning. |
| IMP-010 | Edge dan Brave diperlakukan sebagai preset `chromium` hanya setelah fixture versi browser dalam release matrix lulus. |
| IMP-011 | Duplikat HARUS dideteksi dari pasangan URL ternormalisasi dan username ternormalisasi. Jika keduanya kosong, baris tidak dianggap duplikat otomatis. |
| IMP-012 | Normalisasi username: trim, Unicode NFKC, lalu casefold. Normalisasi URL: trim; tambah `https://` hanya untuk pembandingan bila scheme tidak ada; lowercase scheme/host; IDNA host; hapus fragment dan default port; pertahankan query; ubah root kosong menjadi `/`. Jika parsing gagal, gunakan Unicode NFKC + casefold dari string trim. |
| IMP-013 | Untuk setiap konflik dan secara batch, preview HARUS menawarkan `Skip`, `Update`, atau `Keep Both`. Default adalah `Skip`. |
| IMP-014 | `Update` mempertahankan UUID, created_at, dan history item lama; field yang dipetakan menimpa field lama, field tidak dipetakan dipertahankan, dan pergantian password mengikuti CRD-011. `Keep Both` membuat UUID baru. |
| IMP-015 | ImportPreview HARUS terikat pada sesi dan revision vault saat dibuat, disimpan hanya di memori, serta kedaluwarsa setelah 30 menit atau ketika sesi berakhir. Commit pada vault revision berbeda harus menghitung ulang konflik dan meminta preview baru. |
| IMP-016 | Commit HARUS satu transaksi atomik untuk seluruh baris valid yang dipilih. Jika gagal, tidak ada baris yang diterapkan. |
| IMP-017 | Header persis profil spreadsheet EXP-005 HARUS mengaktifkan mapping LocalVault otomatis: tags dipisahkan `;`, favorite menerima `true/false`, timestamp ISO-8601, `custom_fields_json` divalidasi, dan `_localvault_escape_map` mengembalikan formula-escaped value secara lossless. Generic favorite menerima case-insensitive `true/false`, `1/0`, `yes/no`, atau `ya/tidak`; category/tag yang belum ada dibuat saat commit. |

Deteksi delimiter mem-parsing 20 logical record pertama dengan masing-masing kandidat. Kandidat dengan error quote dibuang; pilih kandidat dengan jumlah kolom modal >1 yang konsisten pada record terbanyak, lalu jumlah kolom terbesar. Tie-breaker adalah koma, titik koma, lalu tab. Bila semua kandidat menghasilkan satu kolom, default koma dipakai dan UI meminta pengguna mengonfirmasi atau mengganti delimiter.

### 5.2 Ekspor plaintext

| ID | Persyaratan |
|---|---|
| EXP-001 | Ekspor HARUS menyediakan profil `spreadsheet`, `chromium`, dan `firefox` dengan scope `all`, `filtered`, atau `selected`. |
| EXP-002 | Setiap ekspor HARUS meminta master password ulang dalam request yang sama, memverifikasinya terhadap wrapped DEK, dan menampilkan peringatan bahwa output plaintext dapat dibaca siapa pun. Sesi unlocked saja tidak cukup. |
| EXP-003 | Respons ekspor HARUS di-stream langsung dari memori ke klien, tidak boleh membuat file sementara di host, dan harus memuat `Cache-Control: no-store, no-cache, must-revalidate`, `Pragma: no-cache`, serta `Expires: 0`. |
| EXP-004 | Respons HARUS memakai `Content-Disposition: attachment` dengan nama aman `localvault-<profile>-<YYYYMMDD-HHMMSSZ>.csv`. |
| EXP-005 | Profil `spreadsheet` HARUS menggunakan UTF-8 BOM, delimiter koma, CRLF, quoting RFC 4180, dan header `name,url,username,password,category,tags,favorite,notes,created_at,updated_at,custom_fields_json,_localvault_escape_map`. Tags dipisahkan `;`; custom field berupa array JSON minified dengan `label`, `type`, dan `value`; kolom terakhir berisi daftar header yang di-escape untuk round-trip. |
| EXP-006 | Profil `chromium` HARUS menggunakan UTF-8 tanpa BOM, koma/CRLF, dan header persis `name,url,username,password,note`. `note` berasal dari notes; field LocalVault lain tidak diekspor. |
| EXP-007 | Profil `firefox` HARUS menggunakan UTF-8 tanpa BOM, koma/CRLF, dan header persis `url,username,password,httpRealm,formActionOrigin,guid,timeCreated,timeLastUsed,timePasswordChanged`. Realm/action kosong, GUID berasal dari UUID, dan waktu berupa Unix epoch millisecond. |
| EXP-008 | Nilai yang dimulai `=`, `+`, `-`, atau `@` pada profil `spreadsheet` HARUS diawali apostrof untuk mitigasi formula injection dan nama field dicatat di `_localvault_escape_map`. Profil browser tidak boleh mengubah field karena interoperabilitas, tetapi UI harus memperingatkan risikonya. |
| EXP-009 | Scope `filtered` HARUS mengirim snapshot query/filter/sort eksplisit; scope `selected` HARUS mengirim UUID eksplisit. Server harus menghitung scope dan tidak mempercayai data baris dari klien. |
| EXP-010 | Request, kegagalan, nama file, dan metrik ekspor TIDAK BOLEH mencatat master password atau konten CSV. |

## 6. Backup, restore, reset, dan upgrade

| ID | Persyaratan |
|---|---|
| BAK-001 | Setelah setiap mutasi vault berhasil, server HARUS membuat backup terenkripsi yang merepresentasikan hasil commit. Mutasi baru dianggap sukses kepada klien setelah backup wajib berhasil. |
| BAK-002 | Jika penulisan backup gagal, server HARUS mengembalikan kegagalan dan melakukan rollback transaksi vault sehingga state sebelum mutasi tetap aktif. |
| BAK-003 | Retensi HARUS menyimpan 10 snapshot versi terbaru tanpa membedakan kind dan satu snapshot `daily` untuk masing-masing dari 30 tanggal UTC terbaru yang memiliki snapshot harian. Snapshot yang memenuhi salah satu bucket tidak boleh dihapus. |
| BAK-004 | Server HARUS membuat tepat satu snapshot `daily` per tanggal UTC ketika aplikasi berjalan: pada startup/first mutation tanggal itu atau scheduler sesudah `00:05Z`. Snapshot boleh memiliki revision yang sama dengan hari sebelumnya dan dipertahankan selama 30 tanggal UTC terbaru. Kegagalan memicu tray warning dan retry setiap jam sampai berhasil. |
| BAK-005 | Backup HARUS menyimpan envelope terenkripsi, metadata non-rahasia yang dibutuhkan untuk restore, dan manifest ber-checksum; tidak boleh menyimpan plaintext payload, password, atau key tak terbungkus. |
| BAK-006 | Backup otomatis disimpan di `LocalVault-Data/backups` dengan nama `lv-<vault-id>-r<revision>-<timestamp>-<kind>.lvbak`. Penulisan memakai file sementara terenkripsi dalam folder yang sama, `fsync`, atomic rename, lalu pembaruan index. |
| BAK-007 | Pengguna HARUS dapat membuat backup manual dan langsung mengunduh `.lvbak`. Backup manual memakai envelope revision saat ini, tidak plaintext, disimpan di folder backup, dan ikut bucket 10 snapshot versi terbaru pada BAK-003. |
| BAK-008 | Pengguna HARUS dapat memilih backup lokal terindeks atau mengunggah `.lvbak` untuk restore. Restore memvalidasi format, vault/schema compatibility, checksum, autentikasi AEAD, dan kemampuan membuka payload sebelum mengubah vault aktif. Untuk backup dengan vault ID/DEK yang sama, server HARUS memakai DEK sesi aktif tanpa reautentikasi; bila DEK aktif tidak dapat membuka kandidat, UI meminta master/recovery yang valid saat snapshot dibuat semata-mata sebagai material dekripsi backup. |
| BAK-009 | Sebelum restore, schema migration, reset vault, dan bulk destructive action, snapshot `pre-operation` tervalidasi HARUS dibuat. Kegagalan snapshot membatalkan operasi. |
| BAK-010 | Restore HARUS atomik: tulis database kandidat, verifikasi ulang, flush, lalu atomic replace. Crash sebelum replace mempertahankan vault lama; crash sesudah replace menghasilkan vault baru yang lengkap. |
| BAK-011 | Restore sukses HARUS membatalkan semua sesi, memaksa seluruh klien reload, dan mengharuskan unlock terhadap vault hasil restore. |
| BAK-012 | Restore versi schema lebih baru daripada aplikasi HARUS ditolak. Restore versi lebih lama HARUS menjalani migrasi bertahap pada kandidat setelah pre-operation snapshot. |
| BAK-013 | Reset vault HARUS meminta sesi unlocked, master password saat ini, frasa konfirmasi `RESET LOCALVAULT`, master password baru, serta pilihan recovery. Reset membuat vault ID/DEK baru dan recovery baru bila dipilih, lalu vault kosong tanpa membuka kembali endpoint setup. |
| BAK-014 | Penggantian master password HARUS membungkus ulang DEK yang sama, bukan mengenkripsi ulang payload. Operasi meminta master lama dan master baru, strength warning yang dapat diabaikan, serta snapshot pre-operation. Backup historis bersifat immutable: saat vault aktif masih unlocked, DEK aktif dapat membuka backup satu-vault; untuk disaster restore tanpa vault aktif, backup dapat memerlukan master/recovery yang valid ketika dibuat. UI harus memperingatkan hal ini sebelum pergantian/rotasi dan key lama tidak dapat dicabut dari salinan backup lama yang telah diekspor. |
| BAK-015 | Upgrade aplikasi dilakukan manual dengan menghentikan aplikasi, mengganti artefak launcher/aplikasi, dan menjalankannya kembali. Migrasi schema tidak boleh dimulai sebelum snapshot dan harus dapat rollback atomik. |

## 7. Persyaratan keamanan dan kriptografi

### 7.1 Threat model dan batas perlindungan

LocalVault v1 melindungi kerahasiaan dan integritas data-at-rest ketika host tidak sedang memiliki sesi unlocked dan file vault/backup disalin oleh pihak yang tidak mengetahui master password atau recovery key. LocalVault v1 secara eksplisit **tidak** melindungi terhadap:

- penyadapan, manipulasi, atau man-in-the-middle pada HTTP LAN;
- injeksi JavaScript oleh pihak yang mampu mengubah lalu lintas LAN;
- brute force online terhadap endpoint unlock;
- host/OS/browser yang terkompromi, malware, keylogger, screen capture, atau pembacaan process memory;
- pengguna atau penyerang yang memperoleh sesi unlocked;
- pembacaan clipboard setelah secret disalin;
- kehilangan data ketika master password hilang dan recovery key tidak tersedia.

Peringatan ini bukan alasan untuk menurunkan kontrol data-at-rest di bawah ini.

### 7.2 Envelope encryption

| ID | Persyaratan |
|---|---|
| SEC-001 | Setup HARUS membuat DEK 32 byte menggunakan CSPRNG OS. DEK tidak berasal dari master password. |
| SEC-002 | Seluruh payload vault HARUS diserialisasi sebagai UTF-8 JSON kanonik, lalu dienkripsi sebagai satu AEAD menggunakan AES-256-GCM dan DEK. |
| SEC-003 | Setiap enkripsi payload dan pembungkusan key HARUS memakai nonce 12 byte baru dari CSPRNG. Implementasi harus menolak nonce yang sama dengan nonce aktif lain untuk DEK/key yang sama dan tidak boleh memakai counter yang dapat mundur saat restore. |
| SEC-004 | AAD payload HARUS berupa encoding panjang-terbatas dari tuple `("LocalVault", "payload", 1, vault_id, schema_version, vault_revision)`. Mengubah salah satu elemen harus menggagalkan autentikasi. |
| SEC-005 | Master password HARUS diturunkan langsung menjadi KEK 32 byte memakai Argon2id dengan salt acak 16 byte. Baseline v1: `m_cost=65536 KiB`, `t_cost=3`, `parallelism=1`, output 32 byte. Salt, algoritme, versi, dan parameter disimpan bersama envelope. |
| SEC-006 | Master KEK HARUS membungkus DEK menggunakan AES-256-GCM. AAD wrap HARUS mengikat `("LocalVault", "master-wrap", 1, vault_id, schema_version)`. |
| SEC-007 | Pergantian master password HARUS membuat salt baru, menurunkan KEK baru, dan membungkus DEK yang sama dengan nonce baru. Ciphertext payload tidak boleh berubah kecuali ada mutasi payload lain. |
| SEC-008 | Kegagalan autentikasi GCM pada payload atau wrapped key HARUS dianggap korupsi/credential salah; plaintext unauthenticated tidak boleh digunakan atau dikembalikan. |
| SEC-009 | Tag GCM 128-bit TIDAK BOLEH dipotong. Ciphertext dan tag boleh disimpan terpisah atau sebagai keluaran library gabungan selama format backup terdokumentasi. |
| SEC-010 | Implementasi HARUS menggunakan library kriptografi yang terpelihara dan primitive konstan-waktu sejauh tersedia. AES, GCM, Argon2id, HKDF, SHA-256, base32, dan random sampling TIDAK BOLEH diimplementasikan sendiri. |

### 7.3 Recovery key

| ID | Persyaratan |
|---|---|
| SEC-011 | Recovery key opsional HARUS berasal dari seed CSPRNG 32 byte yang independen dari DEK dan master password. |
| SEC-012 | Format canonical recovery key adalah prefix `LV1`, encoding Crockford Base32 tanpa padding dari seed 256-bit (52 karakter), dan checksum 8 karakter Base32 dari 40 bit pertama `SHA-256(UTF8("LocalVault recovery v1") ∥ seed)`. Tampilan memakai huruf kapital dan grup empat karakter dipisahkan `-`; parser mengabaikan spasi/hyphen dan menerima pemetaan Crockford `O→0`, `I/L→1`. |
| SEC-013 | Recovery KEK HARUS diturunkan menggunakan HKDF-SHA-256 dengan IKM seed, salt byte UUID vault, info UTF-8 `LocalVault recovery KEK v1`, dan output 32 byte. |
| SEC-014 | Recovery KEK membungkus DEK secara terpisah dengan AES-256-GCM, nonce baru, dan AAD `("LocalVault", "recovery-wrap", 1, vault_id, schema_version)`. Seed dan recovery KEK tidak boleh disimpan. |
| SEC-015 | Recovery yang berhasil HARUS meminta master password baru, membuat salt/master KEK baru, serta membuat dan menampilkan recovery key baru. Wrapped recovery lama harus dihapus sehingga key lama tidak berlaku untuk vault aktif atau snapshot baru; salinan backup historis tetap mengikuti BAK-014. |
| SEC-016 | Recovery key hanya boleh muncul pada response setup, enable, rotate, atau recovery yang membuatnya. Response berikutnya hanya menyatakan `recovery_enabled`. |
| SEC-017 | Checksum yang salah HARUS ditolak sebelum operasi Argon/HKDF/GCM dengan pesan format generik yang tidak membuka informasi envelope. |
| SEC-018 | Pengguna dengan sesi unlocked HARUS dapat enable, rotate, atau disable recovery key. Enable/rotate menghasilkan key baru satu kali; disable menghapus wrapped recovery setelah snapshot pre-operation. |

### 7.4 Data rahasia, memori, transport, dan log

| ID | Persyaratan |
|---|---|
| SEC-019 | Nama, URL, username, password, kategori, tag, favorit, catatan, custom field, history, timestamp item, filter tersimpan, dan general settings pengguna HARUS berada di ciphertext payload. |
| SEC-020 | PostgreSQL dan backup TIDAK BOLEH memiliki kolom atau indeks plaintext untuk field Credential, Category, tag, history, atau custom field. |
| SEC-021 | Plaintext payload, DEK, KEK, master password, dan recovery seed hanya BOLEH berada di memori proses/tab yang memerlukannya dan HARUS dihapus secara best-effort saat lock, sesi terakhir berakhir, restore, reset, atau shutdown. |
| SEC-022 | Master password dan recovery key harus ditampung sesingkat mungkin dalam buffer mutable bila runtime memungkinkan; referensi harus dilepas dan buffer di-zeroize best-effort. Tidak ada klaim penghapusan sempurna pada Python, JavaScript, swap, atau garbage collector. |
| SEC-023 | Semua response API, termasuk error, HARUS memakai `Cache-Control: no-store`. Response secret tidak boleh dimasukkan service worker/cache aplikasi. LocalVault TIDAK BOLEH mendaftarkan service worker. |
| SEC-024 | Aplikasi HARUS menonaktifkan CORS; tidak boleh mengirim `Access-Control-Allow-Origin` untuk origin lain. Request state-changing HARUS menolak `Origin` yang tidak sama dengan scheme+Host request. |
| SEC-025 | Host header HARUS berupa loopback, hostname lokal terkonfigurasi, atau alamat interface aktif host pada port persisten; host lain ditolak untuk mengurangi DNS rebinding. |
| SEC-026 | HTML HARUS mengirim CSP minimal `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' ws:; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`, serta `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, dan `Permissions-Policy` yang menolak kapabilitas yang tidak dipakai. |
| SEC-027 | `unsafe-inline`, `unsafe-eval`, external origin, dan remote source map TIDAK BOLEH ada pada build release. HSTS tidak dikirim karena v1 tidak memakai TLS. |
| SEC-028 | Log TIDAK BOLEH memuat password item, master password, recovery key/seed, DEK/KEK, token/ticket, ciphertext lengkap, wrapped key lengkap, isi catatan, custom field, body request sensitif, atau konten/baris CSV. |
| SEC-029 | Error log boleh memuat timestamp, level, correlation ID, route template, status, error code, vault revision, entity UUID, dan stack trace yang sudah disanitasi. Query string endpoint WebSocket dan header Authorization harus selalu di-redact. |
| SEC-030 | Banner persisten di seluruh setup, lock, dan aplikasi unlocked HARUS menyatakan `HTTP LAN tidak terenkripsi` dan membuka dialog threat model. Banner tidak dapat ditutup permanen. |
| SEC-031 | Halaman setup/security HARUS menampilkan peringatan tetap bahwa setup tanpa code, master password lemah, dan unlock tanpa throttling meningkatkan risiko. |
| SEC-032 | Aplikasi TIDAK BOLEH membuat koneksi keluar selain response ke koneksi host/LAN yang masuk. Pembukaan URL hanya dilakukan browser setelah klik pengguna dengan mitigasi reverse-tabnabbing (`noopener,noreferrer`). |

## 8. Model data kanonik

### 8.1 Aturan umum

| ID | Persyaratan |
|---|---|
| DAT-001 | Semua ID entity HARUS UUID v4 lowercase dengan hyphen. Server membuat ID dan menolak ID dari klien pada create, kecuali GUID sumber impor disimpan sebagai metadata custom dan bukan primary ID. |
| DAT-002 | Semua timestamp aplikasi HARUS UTC ISO-8601 dengan millisecond dan suffix `Z`, contoh `2026-07-20T10:15:30.123Z`. Timestamp CSV Firefox diekspor khusus sebagai epoch millisecond. |
| DAT-003 | `revision` HARUS integer positif. Credential baru dimulai pada 1; `vault_revision` dimulai pada 1 saat setup dan bertambah tepat satu per transaksi mutasi, termasuk transaksi massal. |
| DAT-004 | JSON API memakai UTF-8, nama field `snake_case`, boolean JSON, `null` eksplisit untuk field opsional, dan enum lowercase. Field tak dikenal pada request mutasi ditolak dengan `422 VALIDATION_ERROR`. |
| DAT-005 | Urutan array categories, tags, credentials, custom fields, dan history dalam JSON kanonik HARUS deterministik sebelum enkripsi agar hasil dapat diuji: urut UUID, kecuali custom field memakai `(order,id)` dan history memakai timestamp turun lalu ID. |
| DAT-006 | JSON kanonik HARUS mendefinisikan sorting key, encoding string, representasi angka, dan tanpa whitespace melalui serializer standar yang diuji fixture. |

### 8.2 Entity `Credential`

Semua field berikut berada di payload terenkripsi.

| Field | Tipe | Aturan |
|---|---|---|
| `id` | UUID | immutable |
| `name` | string | wajib; trim; 1–300 karakter |
| `url` | string \| null | opsional; nilai asli dipertahankan |
| `username` | string \| null | username atau email |
| `password` | string | boleh kosong |
| `category_id` | UUID \| null | referensi Category |
| `tags` | string[] | unik NFKC-casefold; urut tampilan |
| `favorite` | boolean | default `false` |
| `notes` | string | default kosong |
| `custom_fields` | CustomField[] | default kosong |
| `password_history` | PasswordHistoryEntry[] | maksimal lima |
| `created_at` | timestamp | immutable |
| `updated_at` | timestamp | waktu mutasi terakhir |
| `deleted_at` | timestamp \| null | `null` bila aktif |
| `revision` | integer | optimistic concurrency |

### 8.3 Entity `CustomField`

| Field | Tipe | Aturan |
|---|---|---|
| `id` | UUID | dibuat server |
| `label` | string | 1–100 karakter; unik per Credential |
| `type` | enum | `text` atau `secret` |
| `value` | string | maksimum 100.000 karakter |
| `order` | integer | mulai 0; server menormalkan agar kontigu |

### 8.4 Entity `PasswordHistoryEntry`

| Field | Tipe | Aturan |
|---|---|---|
| `id` | UUID | dibuat server |
| `password` | string | password lama, terenkripsi sebagai bagian payload |
| `changed_at` | timestamp | saat password diganti |

### 8.5 Entity `Category`

| Field | Tipe | Aturan |
|---|---|---|
| `id` | UUID | dibuat server |
| `name` | string | trim; 1–100 karakter; unik NFKC-casefold |
| `created_at` | timestamp | UTC |
| `updated_at` | timestamp | UTC |
| `revision` | integer | mulai 1 |

Tag adalah string dalam katalog `VaultPayload.tags`; tag tidak memiliki warna, ID, atau metadata tambahan pada v1.

### 8.6 Entity `VaultSettings`

| Field | Tipe | Default |
|---|---|---|
| `language` | `id` \| `en` | `id` |
| `tag_filter_mode` | `and` \| `or` | `and` |
| `default_sort` | object `{field,direction}` | `{name,asc}` |
| `page_size` | `25` \| `50` \| `100` | `50` |
| `warning_acknowledgements` | string[] | kosong; tidak pernah menyembunyikan banner HTTP |

Tema tidak disimpan sebagai pilihan karena selalu mengikuti `prefers-color-scheme`. Bahasa disalin ke `config.json` hanya sebagai preferensi non-rahasia agar lock screen memakai pilihan terakhir; payload adalah sumber kebenaran setelah unlock.

### 8.7 Entity `VaultEnvelope`

Field ini adalah satu row aktif di PostgreSQL dan seluruh nilai binary disimpan sebagai `bytea`, bukan Base64.

| Field | Tipe | Rahasia saat disimpan |
|---|---|---|
| `vault_id` | UUID | tidak |
| `schema_version` | integer | tidak |
| `vault_revision` | integer | tidak |
| `format_version` | integer (`1`) | tidak |
| `kdf_algorithm` | string (`argon2id`) | tidak |
| `kdf_salt` | 16-byte BLOB | tidak |
| `kdf_m_cost_kib` | integer | tidak |
| `kdf_t_cost` | integer | tidak |
| `kdf_parallelism` | integer | tidak |
| `master_wrap_nonce` | 12-byte BLOB | tidak |
| `wrapped_dek_master` | BLOB + tag | ya, tetapi terenkripsi |
| `recovery_wrap_nonce` | 12-byte BLOB \| null | tidak |
| `wrapped_dek_recovery` | BLOB + tag \| null | ya, tetapi terenkripsi |
| `payload_nonce` | 12-byte BLOB | tidak |
| `payload_ciphertext` | BLOB + tag | ya, terenkripsi |
| `envelope_checksum` | 32-byte SHA-256 | tidak; untuk deteksi kerusakan format sebelum AEAD |

`envelope_checksum` bukan kontrol autentikasi dan tidak boleh menggantikan verifikasi GCM.

### 8.8 Entity `Session`

Entity hanya ada di memori server.

| Field | Tipe | Aturan |
|---|---|---|
| `session_id` | UUID | aman untuk log |
| `token_digest` | 32-byte | SHA-256 token; raw token hanya dikembalikan sekali |
| `tab_instance_id` | UUID | ditetapkan saat koneksi owner pertama |
| `created_at` | timestamp | UTC |
| `ws_connected` | boolean | status owner |
| `disconnect_deadline` | timestamp \| null | maksimum 10 detik |
| `client_label` | string | browser/OS generik, tanpa fingerprinting |

### 8.9 Entity `ImportPreview` dan `ImportConflict`

`ImportPreview` hanya ada di memori dan memiliki `id`, `session_id`, `base_vault_revision`, `profile`, `delimiter`, `mapping`, `valid_rows`, `invalid_rows`, `conflicts`, `created_at`, dan `expires_at`. Raw upload dan parsed values harus dibuang saat commit, expiry, lock, atau pembatalan.

`ImportConflict` memiliki `row_number`, `existing_credential_id`, `normalized_url_hash`, `normalized_username_hash`, `resolution` (`skip|update|keep_both`), dan `reason`. Hash hanya hidup di memori dan tidak masuk log/response bila dapat dipakai menebak secret; response UI cukup mengirim row number, existing UUID, serta data display yang memang boleh dilihat sesi unlocked.

### 8.10 Entity `BackupManifest`

| Field | Tipe | Aturan |
|---|---|---|
| `format` | string | `localvault-backup` |
| `format_version` | integer | `1` |
| `backup_id` | UUID | unik |
| `vault_id` | UUID | target vault |
| `schema_version` | integer | schema payload |
| `vault_revision` | integer | revision snapshot |
| `created_at` | timestamp | UTC |
| `kind` | enum | `mutation`, `daily`, `manual`, `pre_operation` |
| `operation` | string \| null | jenis pre-operation tanpa data rahasia |
| `envelope_sha256` | hex string | checksum seluruh bytes envelope |
| `application_version` | semver | pembuat backup |

File `.lvbak` HARUS merupakan container versioned berisi manifest UTF-8 dan bytes `VaultEnvelope`; parser memakai length-prefix dan magic `LOCALVAULT_BACKUP\0` sehingga tidak bergantung pada ekstensi.

### 8.11 Skema PostgreSQL yang diizinkan

| Table | Isi yang diizinkan |
|---|---|
| `app_meta` | schema container dan application migration state |
| `users` | identitas akun dan password hash Argon2id, tanpa isi vault |
| `vault_envelopes` | satu `VaultEnvelope` aktif per user |
| `backup_index` | `BackupManifest`, user, path relatif, status validasi, bucket retensi |

Tidak boleh ada table credential/category/tag/history/session/import plaintext. PostgreSQL HARUS memakai transaksi untuk perubahan envelope dan index backup; isi payload rahasia hanya boleh berada pada kolom ciphertext `bytea`.

## 9. Kontrak antarmuka

### 9.1 Aturan REST umum

| ID | Persyaratan |
|---|---|
| API-001 | Base path HARUS `/api/v1`. Selain download/upload, request dan response memakai `application/json; charset=utf-8`. |
| API-002 | Semua response API HARUS memiliki `X-Request-ID`; client boleh mengirim UUID valid atau server membuatnya. |
| API-003 | Error HARUS memakai `application/problem+json` dengan field `type`, `title`, `status`, `code`, `detail`, `request_id`, dan opsional `errors` yang tidak mengandung secret. |
| API-004 | Status utama: `200/201/204` sukses, `400` format, `401` sesi/reauth gagal, `403` origin/aksi ditolak, `404` entity, `409` setup/conflict/state, `413` terlalu besar, `422` validasi, `423` vault locked, `500` internal, `507` penyimpanan/backup gagal. |
| API-005 | Create HARUS mengembalikan `201` dan entity; mutation lain mengembalikan entity/result serta `vault_revision`. Delete/lock tanpa body memakai `204`. |
| API-006 | List memakai cursor opaque in-memory atau offset stabil dengan default 50/maksimum 100. Response memuat `items`, `page`, `page_size`, `total`, dan `vault_revision`. |
| API-007 | Update/delete satu entity HARUS meminta `If-Match: "<revision>"`. Header hilang mendapat `428 PRECONDITION_REQUIRED`. |
| API-008 | Semua operasi yang memerlukan unlocked vault harus menolak token invalid dengan `401 SESSION_INVALID` dan frontend menghapus token lalu kembali ke lock screen. |

### 9.2 Endpoint setup dan sesi

| Method dan path | Auth | Request/response normatif |
|---|---|---|
| `GET /api/v1/status` | publik | Mengembalikan `setup_required`, versi, `recovery_enabled`, port, dan `http_lan_warning=true`; tidak mengungkap ID/revision vault. |
| `POST /api/v1/setup` | publik, hanya sekali | Request SET-003. Response `201` berisi token sesi dan recovery key opsional satu kali. |
| `POST /api/v1/sessions/unlock` | publik | `{master_password,tab_instance_id}` → token, session ID, vault revision. |
| `POST /api/v1/sessions/recover` | publik | `{recovery_key,new_master_password,confirm_new_master_password,weak_password_acknowledged,tab_instance_id}` → token dan recovery key baru satu kali. |
| `GET /api/v1/sessions/current` | Bearer | Metadata sesi dan vault revision, tanpa token. |
| `POST /api/v1/sessions/lock` | Bearer | Membatalkan sesi pemanggil. |
| `POST /api/v1/sessions/lock-all` | Bearer | Membatalkan semua sesi. |
| `POST /api/v1/sessions/event-ticket` | Bearer | Ticket CSPRNG 256-bit, single-use, berlaku 10 detik untuk WebSocket; ticket tidak boleh dicatat. |

Browser WebSocket tidak dapat mengirim header Authorization arbitrer secara portabel. Karena itu token sesi tetap hanya dikirim melalui Authorization ke endpoint ticket; WebSocket memakai ticket singkat sekali pakai, bukan token sesi di URL.

### 9.3 Endpoint Credential, Category, dan tag

| Method dan path | Fungsi |
|---|---|
| `GET /api/v1/credentials` | List/search/filter/sort aktif atau Trash; query sesuai CRD-017–020. |
| `POST /api/v1/credentials` | Membuat Credential. |
| `GET /api/v1/credentials/{id}` | Mengambil detail lengkap termasuk history; nilai secret dikirim karena sesi unlocked, tetapi UI tetap mask. |
| `PUT /api/v1/credentials/{id}` | Mengganti entity lengkap dengan `If-Match`, `base_revision`, dan resolusi konflik opsional. |
| `POST /api/v1/credentials/{id}/trash` | Soft delete dengan `If-Match`. |
| `POST /api/v1/credentials/{id}/restore` | Restore dengan `If-Match`. |
| `DELETE /api/v1/credentials/{id}` | Purge permanen item Trash dengan `If-Match`; item aktif ditolak. |
| `POST /api/v1/credentials/bulk` | `{action,ids:[{id,revision}],arguments}`; atomik sesuai TRS-005–007. |
| `POST /api/v1/trash/empty` | Empty Trash setelah `{confirmation,count_expected}`; server menolak count stale. |
| `GET/POST /api/v1/categories` | List/create Category. |
| `PUT/DELETE /api/v1/categories/{id}` | Rename/delete dengan `If-Match`. |
| `GET/POST /api/v1/tags` | List/create tag. |
| `POST /api/v1/tags/rename` | Rename/merge global dengan source, target, dan revision vault. |
| `DELETE /api/v1/tags/{name}` | Hapus global menggunakan nama URL-encoded dan revision vault. |
| `POST /api/v1/password-generator` | Membuat satu password sesuai GEN-001–005. |

List Credential HARUS mengembalikan field yang diperlukan tabel tetapi boleh menunda notes, custom field values, dan history sampai detail diminta. Semua tetap berasal dari payload in-memory, bukan kolom plaintext.

### 9.4 Endpoint impor dan ekspor

| Method dan path | Fungsi |
|---|---|
| `POST /api/v1/imports/previews` | Multipart CSV + JSON profile/mapping awal; membuat preview. |
| `GET /api/v1/imports/previews/{id}` | Mengambil ringkasan/sampel preview milik sesi. |
| `PUT /api/v1/imports/previews/{id}` | Mengubah mapping dan resolusi konflik lalu menghitung ulang preview. |
| `GET /api/v1/imports/previews/{id}/errors.csv` | Streaming laporan error tanpa nilai sumber. |
| `POST /api/v1/imports/previews/{id}/commit` | Commit baris valid dengan base vault revision. |
| `DELETE /api/v1/imports/previews/{id}` | Membatalkan dan membersihkan preview. |
| `POST /api/v1/exports` | JSON master password, profile, scope, filter/ID; streaming CSV plaintext. |

### 9.5 Endpoint backup dan settings

| Method dan path | Fungsi |
|---|---|
| `GET /api/v1/backups` | Daftar manifest backup terindeks, tanpa ciphertext/path absolut. |
| `POST /api/v1/backups/manual` | Membuat snapshot manual dan mengembalikan manifest. |
| `GET /api/v1/backups/{backup_id}/download` | Streaming backup terenkripsi. |
| `POST /api/v1/backups/restore` | Restore dari `backup_id` atau multipart `.lvbak`; meminta key pembuka yang sesuai. |
| `GET /api/v1/settings/security` | KDF params, `recovery_enabled`, dan warning; tanpa wrapped key. |
| `PUT /api/v1/settings/security/master-password` | Ganti master dengan master lama/baru. |
| `POST /api/v1/settings/security/recovery-key` | Enable/rotate dan kembalikan key satu kali. |
| `DELETE /api/v1/settings/security/recovery-key` | Disable recovery. |
| `POST /api/v1/settings/security/reset-vault` | Reset sesuai BAK-013. |
| `GET/PUT /api/v1/settings/general` | Ambil/ubah `VaultSettings` dengan vault revision. |
| `GET/PUT /api/v1/settings/host` | Ambil/ubah port dan autostart non-rahasia; perubahan port tervalidasi dan mengembalikan `restart_required=true`, autostart diterapkan user-level melalui launcher. |

### 9.6 WebSocket event

| ID | Persyaratan |
|---|---|
| API-009 | Endpoint HARUS `GET /api/v1/events?ticket=<single-use-ticket>` dengan upgrade WebSocket. Query string harus di-redact dari access log. |
| API-010 | Ticket harus dikonsumsi atomik, terikat session/tab, dan tidak dapat digunakan ulang. |
| API-011 | Event HARUS berbentuk `{event_id,type,entity_type,entity_id,entity_revision,vault_revision,occurred_at}` dan TIDAK BOLEH memuat nama, URL, username, password, tag, catatan, atau nilai rahasia lain. |
| API-012 | Tipe minimal: `credential.created`, `credential.updated`, `credential.trashed`, `credential.restored`, `credential.purged`, `category.changed`, `tag.changed`, `settings.changed`, `vault.locked`, dan `vault.reload_required`. |
| API-013 | Setelah menerima event, klien HARUS mengambil data terbaru melalui REST atau invalidasi cache; event bukan sumber data entity. |
| API-014 | Event mutation HARUS diterima semua klien lain paling lambat satu detik setelah transaksi dan backup commit pada LAN referensi. |
| API-015 | WebSocket HARUS mengirim heartbeat setiap 20 detik dan menganggap koneksi putus setelah dua heartbeat gagal, tanpa memperkenalkan idle timeout selama koneksi sehat. |
| API-016 | Setelah reconnect, klien mengirim `last_seen_vault_revision`. Jika ada gap, server mengirim `vault.reload_required`; server tidak wajib menyimpan event secret atau event log persisten. |

## 10. Antarmuka pengguna dan internasionalisasi

### 10.1 Struktur layar

| Area | Perilaku wajib |
|---|---|
| Setup | Penjelasan risiko, master password/konfirmasi, strength indicator, opsi recovery, pilihan bahasa, dan acknowledgement. |
| Lock/recovery | Master password, aksi unlock, tautan recovery, status host non-rahasia, dan banner HTTP. |
| Vault | App bar, pencarian, filter, tabel/list, toolbar aksi massal, serta panel detail/edit. |
| Trash | Daftar item terhapus, sisa hari retensi, restore, purge, dan empty Trash. |
| Import | Pilih preset/file, delimiter, mapping, preview, resolusi konflik, laporan error, commit. |
| Export | Profile, scope, ringkasan jumlah, peringatan plaintext, dan reautentikasi. |
| Backup | Daftar manifest, backup manual/download, upload/restore, status validasi. |
| Settings | General, language, security, master/recovery/reset, port/autostart dengan penanda restart bila perlu. |

### 10.2 Persyaratan UI/UX

| ID | Persyaratan |
|---|---|
| UIX-001 | Desain HARUS modern, bersih, padat, rapi, dan presisi, dengan hierarchy visual konsisten serta tanpa dekorasi yang mengurangi keterbacaan data. |
| UIX-002 | UI HARUS berupa SPA; navigasi, CRUD, filter, sorting, detail, import, export, dan settings tidak boleh memerlukan full page reload, kecuali reload paksa setelah restore/migrasi. |
| UIX-003 | Desktop ≥1200 px HARUS menampilkan tabel dan panel detail berdampingan. Tablet 768–1199 px memakai tabel/list dan drawer detail. Ponsel 360–767 px memakai list satu kolom dan detail layar penuh. |
| UIX-004 | Tabel desktop minimal menampilkan favorite, name, username, URL/host, category, tags, updated, dan menu aksi; kolom boleh disembunyikan progresif pada lebar lebih kecil tanpa menghilangkan akses melalui detail. |
| UIX-005 | Pencarian lokal mulai memfilter setelah debounce maksimum 100 ms. Filter/sort aktif HARUS terlihat sebagai chip/control dan dapat di-reset satu aksi. |
| UIX-006 | Pemilihan massal HARUS memperlihatkan jumlah terpilih, `pilih halaman`, dan `pilih semua hasil filter`; scope harus dikonfirmasi sebelum tindakan destruktif. |
| UIX-007 | Save yang belum selesai HARUS mencegah penutupan panel/navigasi tanpa dialog `Buang perubahan?`. Secret tidak boleh masuk URL atau browser history. |
| UIX-008 | Setiap request yang melampaui 150 ms HARUS menampilkan progress/skeleton yang tidak mengubah layout secara mengganggu. Tombol submit dinonaktifkan selama request yang sama. |
| UIX-009 | Sukses non-trivial HARUS menghasilkan toast singkat; error HARUS memiliki pesan inline/toast, correlation ID, dan aksi retry bila aman. Error validasi muncul di field dan summary. |
| UIX-010 | Konflik edit HARUS menampilkan waktu/revision terkini dan dua aksi jelas: `Muat ulang` serta `Timpa perubahan saya`; tidak boleh overwrite otomatis. |
| UIX-011 | Tombol reveal/copy HARUS memiliki accessible label yang menyebut field. Setelah copy berhasil, label/toast menyatakan bahwa clipboard tidak dibersihkan otomatis. |
| UIX-012 | Seluruh operasi harus dapat dilakukan dengan keyboard. Focus indicator tidak boleh dihapus dan fokus harus dipindahkan secara logis saat drawer/dialog dibuka atau ditutup. |
| UIX-013 | Shortcut global: `/` fokus pencarian; `Ctrl/Cmd+K` membuka command palette lokal; `Ctrl/Cmd+N` membuat Credential; `Ctrl/Cmd+S` menyimpan form; `Escape` menutup layer teratas; `?` membuka bantuan shortcut. Shortcut tidak aktif saat bertentangan dengan input teks. |
| UIX-014 | Dialog harus focus-trapped, memiliki judul/description terprogram, dapat ditutup Escape kecuali commit destruktif sedang berjalan, dan mengembalikan fokus ke pemicu. |
| UIX-015 | Tema HARUS mengikuti `prefers-color-scheme` secara live. Light dan dark theme harus sama-sama memenuhi target contrast. Tidak ada override tema manual pada v1. |
| UIX-016 | Banner HTTP LAN SEC-030 harus selalu memakan ruang layout yang terlihat, bukan toast sementara atau modal satu kali. |
| UIX-017 | URL eksternal harus ditampilkan sebelum dibuka. Hanya scheme `http`/`https` dapat dibuka langsung; scheme lain memerlukan konfirmasi tambahan dan tidak pernah dibuka otomatis. |
| UIX-018 | Empty, loading, offline/reconnecting, locked, validation, forbidden, storage-full, corrupt-backup, dan server-unavailable state HARUS memiliki tampilan serta tindakan pemulihan spesifik. |

### 10.3 Bahasa dan format

| ID | Persyaratan |
|---|---|
| I18N-001 | UI HARUS lengkap dalam Bahasa Indonesia (`id`) dan English (`en`); default first-run adalah Indonesia tanpa bergantung locale browser. |
| I18N-002 | Tidak boleh ada string user-facing hard-coded di komponen selain identifier teknis, nama produk, dan data pengguna. Build gagal bila key terjemahan hilang di salah satu locale. |
| I18N-003 | Bahasa dapat diubah tanpa reload dan disimpan melalui VaultSettings/config sesuai 8.6. |
| I18N-004 | Timestamp API tetap UTC ISO-8601; UI menampilkan zona waktu browser dan locale aktif, dengan nilai UTC tersedia pada tooltip/detail. |
| I18N-005 | Sorting teks memakai `Intl.Collator` locale aktif dengan opsi numerik; hasil server dan client harus memakai aturan ekuivalen dan UUID sebagai tie-breaker. |
| I18N-006 | Layout HARUS tetap benar untuk string English yang 30% lebih panjang daripada padanan Indonesia; truncation harus menyediakan full accessible name/tooltip. |

## 11. Launcher, operasi, dan observabilitas

| ID | Persyaratan |
|---|---|
| OPS-001 | Tray menu berurutan HARUS menyediakan: `Buka LocalVault`, submenu `Alamat host/LAN`, `Lock semua sesi`, toggle `Mulai otomatis saat login`, dan `Stop LocalVault`. |
| OPS-002 | `Buka LocalVault` membuka `http://127.0.0.1:<port>` pada browser default. Aksi ini tidak boleh memulai instance server kedua. |
| OPS-003 | Submenu alamat HARUS menampilkan loopback dan setiap IPv4 LAN aktif sebagai URL lengkap, dengan aksi `Buka` dan `Salin alamat`. Daftar diperbarui ketika interface berubah. |
| OPS-004 | `Lock semua sesi` HARUS tersedia ketika server berjalan; tray memanggil Session Manager melalui in-process thread-safe control queue, bukan endpoint LAN atau token pengguna. Hasil sukses/gagal ditampilkan sebagai notification native atau tray status tanpa secret. |
| OPS-005 | Autostart default `off` dan hanya memakai mekanisme user-level: Startup shortcut Windows, LaunchAgent macOS, dan XDG autostart `.desktop` Linux. Mengaktifkan membuat entry ke path launcher absolut; menonaktifkan menghapus hanya entry milik LocalVault. Tidak boleh meminta admin/root. |
| OPS-006 | `Stop LocalVault` meminta konfirmasi bila ada sesi aktif, melakukan lock-all, menunggu request mutasi selesai maksimum 10 detik, flush database/log, melepas OS lock, lalu menghentikan proses. Setelah timeout, shutdown tetap dilakukan dan operasi belum commit dianggap gagal. |
| OPS-007 | `config.json` hanya boleh berisi data non-rahasia: format version, port, language pre-unlock, autostart preference, log level, dan instance ID. Perubahan port berlaku setelah restart dan divalidasi 1024–65535. |
| OPS-008 | Log default level `INFO`, satu file aktif maksimum 5 MiB, rotasi maksimal 7 file, UTF-8, dan timestamp UTC. Debug logging release tidak boleh menonaktifkan redaction SEC-028. |
| OPS-009 | Launcher dan server HARUS berada dalam satu OS process: tray/event loop native di main thread dan FastAPI server di worker thread yang disupervisi. Readiness/health dikirim melalui in-process queue dan tidak diekspos sebagai endpoint kontrol. Tray menandai status `starting`, `ready`, `locked/unlocked`, atau `error`. |
| OPS-010 | Startup HARUS menjalankan urutan: resolve data dir, acquire OS lock, uji writability, baca/validasi config, koneksi dan migrasi schema PostgreSQL, purge Trash jatuh tempo, bind server, lalu tandai ready. |
| OPS-011 | Jika vault atau config korup, server tidak boleh membuat vault pengganti diam-diam. Launcher harus berhenti pada safe error state dan mengarahkan pengguna ke restore/log. |
| OPS-012 | Access log HARUS mencatat route template, bukan URL mentah yang berpotensi memuat ticket atau nama tag. |
| OPS-013 | Tray, native notification, startup error, dan dialog launcher HARUS tersedia dalam Indonesia/English, memakai language terakhir di `config.json`, dan default Indonesia. Label OPS-001 adalah versi Indonesia; locale English memakai padanan makna yang setara. |

## 12. Arsitektur referensi

### 12.1 Komponen

| Komponen | Tanggung jawab |
|---|---|
| Portable Launcher/Tray | OS lock, lifecycle server, port/config, alamat LAN, autostart, lock-all, buka browser, shutdown. |
| FastAPI Presentation | REST validation, auth middleware, security headers, static SPA, WebSocket ticket/connection. |
| Session Manager | Token digest in-memory, kepemilikan tab, reconnect grace, lock satu/semua, best-effort clearing. |
| Vault Application Service | Use case, permission state, optimistic concurrency, validation, transaksi dan revision. |
| Crypto Adapter | Argon2id, AES-GCM, HKDF, recovery format/checksum, CSPRNG, zeroization best-effort. |
| Vault Repository | Satu encrypted envelope per user di PostgreSQL, metadata schema, atomic candidate/commit. |
| In-memory Vault Index | Model plaintext unlocked, search/filter/sort; tidak pernah diserialisasi di luar ciphertext/export eksplisit. |
| Import/Export Service | Parser fixture-based, mapping/preview/conflict, streaming CSV, formula mitigation. |
| Backup Manager | Container/manifest, snapshot, retensi, validate, pre-operation, atomic restore. |
| Event Broker | Event non-rahasia setelah commit, WebSocket broadcast, revision gap/reload. |
| React SPA | State/UI responsive, i18n, masking/copy fallback, form/conflict, sessionStorage. |

Dependency HARUS mengarah dari presentation menuju application service, lalu port crypto/repository/backup; domain tidak boleh bergantung pada FastAPI, PostgreSQL, tray toolkit, atau React.

### 12.2 Alur unlock

1. Client membaca status dan mengirim master password serta `tab_instance_id` melalui HTTP LAN dengan peringatan aktif.
2. Session service membaca KDF params, menurunkan master KEK, dan membuka wrapped DEK.
3. Crypto adapter membuka serta mengautentikasi payload menggunakan AAD revision aktif.
4. Payload divalidasi penuh terhadap schema sebelum menjadi state in-memory.
5. Server membuat raw token satu kali, menyimpan digest/session metadata, lalu mengembalikan token dengan `no-store`.
6. Client menyimpan token di `sessionStorage`, meminta event ticket memakai Authorization, dan membuka WebSocket owner.

### 12.3 Alur mutasi dan backup

Mutasi HARUS diserialisasi oleh satu async/process mutation lock karena hanya satu host process diizinkan:

```text
validasi sesi + If-Match
  → clone state revision N
  → terapkan/validasi domain menjadi N+1
  → serialisasi kanonik + nonce baru + AES-GCM
  → PostgreSQL transaction, stage envelope N+1
  → tulis/fsync/atomic-rename backup N+1
  → COMMIT PostgreSQL
  → swap state in-memory
  → broadcast event revision N+1
  → terapkan retensi secara best-effort
```

Jika proses gagal sebelum commit PostgreSQL, state N tetap otoritatif dan backup kandidat menjadi orphan yang diabaikan/dibersihkan saat startup. Jika commit berhasil tetapi broadcast gagal, client menemukan gap melalui `vault_revision`. Penghapusan backup karena retensi tidak boleh membatalkan mutasi yang sudah commit; kegagalannya dicatat dan dicoba lagi.

### 12.4 Alur restore

1. Simpan/terima file hanya sebagai ciphertext dan batasi ukuran container 512 MiB.
2. Parse manifest secara defensif dan verifikasi checksum.
3. Buat snapshot pre-restore dari envelope aktif.
4. Minta material pembuka backup, autentikasi wrapped DEK/payload, validasi schema dan seluruh referensi.
5. Jika perlu, migrasikan kandidat di memori dan enkripsi ulang kandidat dengan nonce baru.
6. Tulis database kandidat di data directory, `fsync`, integrity-check, lalu atomic replace.
7. Invalidasi sesi, clear memory, broadcast `vault.reload_required`, dan minta unlock ulang.

### 12.5 Concurrency dan konsistensi

- Satu mutation lock menjaga urutan total `vault_revision`.
- Read memakai snapshot immutable state terakhir yang sudah commit.
- Semua perubahan dalam satu bulk/import commit mendapat satu `vault_revision`, tetapi masing-masing Credential yang berubah menaikkan revision sendiri satu kali.
- Backup, REST response sukses, dan event selalu merujuk revision commit yang sama.
- Server clock digunakan untuk timestamp; input timestamp klien diabaikan kecuali metadata impor yang secara eksplisit didukung.

### 12.6 Dependency dan build policy

- Versi Python, Node.js build-time, FastAPI, React, TypeScript, asyncpg, PostgreSQL client, Argon2, crypto, CSV parser, tray toolkit, dan PyInstaller HARUS dipin tepat di lockfile release.
- Software bill of materials dan checksum SHA-256 HARUS dihasilkan per artefak.
- Frontend dibangun lebih dahulu; output hashed asset disalin ke resource backend; PyInstaller kemudian membundel backend, launcher, library native, dan aset.
- Pipeline terpisah menjalankan build/test di Windows, macOS, dan Linux. Cross-compilation PyInstaller tidak diterima sebagai bukti kompatibilitas.

## 13. Persyaratan kualitas

### 13.1 Performa dan kapasitas

Perangkat referensi minimum adalah host 64-bit dengan 4 logical CPU ≥2,0 GHz, RAM 8 GiB, SSD, dan klien dengan kelas setara pada LAN ber-RTT ≤10 ms. Pengukuran dilakukan pada build release, 1.000 Credential (masing-masing 2 tag, notes 1 KiB, dan 2 custom field), setelah warm-up, dengan p95 dari 100 operasi kecuali startup.

| ID | Persyaratan |
|---|---|
| QUA-001 | Pencarian, filter, atau sort dari input sampai hasil ter-render HARUS p95 <200 ms untuk 1.000 Credential. |
| QUA-002 | Mutasi normal satu Credential, termasuk enkripsi dan backup lokal, HARUS p95 <500 ms. |
| QUA-003 | Event perubahan HARUS terlihat pada klien LAN lain <1 detik setelah commit pada p99. |
| QUA-004 | Dari launcher mulai sampai endpoint ready dan shell UI interaktif HARUS ≤5 detik, tidak termasuk waktu pengguna/browser eksternal membuka window. |
| QUA-005 | Unlock dengan baseline Argon2id harus selesai ≤5 detik pada perangkat referensi dan tidak boleh menurunkan parameter secara otomatis untuk mencapai target. |
| QUA-006 | Produk HARUS berfungsi dengan vault 1.000 item tanpa paging yang kehilangan hasil, freeze main thread >200 ms, atau penggunaan memori host steady-state >512 MiB untuk dataset fixture. |

### 13.2 Kompatibilitas dan responsivitas

| ID | Persyaratan |
|---|---|
| QUA-007 | Release HARUS lulus smoke dan regression suite pada dua versi stabil terbaru Chrome, Edge, Firefox, serta Safari stabil terbaru saat release. Versi exact dicatat di release matrix. |
| QUA-008 | Release HARUS diuji pada viewport 360×800, 768×1024, dan 1440×900 dengan zoom 100% dan 200%, tanpa horizontal overflow halaman atau control yang tidak dapat dijangkau. |
| QUA-009 | Paket Windows, macOS, dan Linux HARUS diuji di mesin bersih tanpa Python/Node, termasuk launch, setup, restart, LAN access, tray, autostart, upgrade, dan restore. |
| QUA-010 | Data yang dibuat oleh satu versi schema pada OS mana pun HARUS dapat dipindahkan bersama folder portable dan dibuka pada build OS lain dengan versi aplikasi/schema kompatibel. |

### 13.3 Aksesibilitas

| ID | Persyaratan |
|---|---|
| QUA-011 | UI HARUS menargetkan WCAG 2.2 AA: contrast teks normal ≥4.5:1, teks besar ≥3:1, komponen/focus indicator ≥3:1. |
| QUA-012 | Semua control HARUS memiliki accessible name, state, role, keyboard operation, dan target pointer minimum 24×24 CSS px atau spacing yang memenuhi WCAG 2.2. |
| QUA-013 | Status toast, error, copy, reconnect, dan selesai loading HARUS diumumkan melalui live region dengan prioritas yang tepat tanpa membocorkan secret yang masked. |
| QUA-014 | Mask/reveal tidak boleh mengandalkan warna atau ikon saja; tabel/list memiliki heading/label semantik; reduced motion dihormati. |

### 13.4 Reliabilitas dan privasi

| ID | Persyaratan |
|---|---|
| QUA-015 | Kill/power-loss test di setiap titik alur mutasi/restore HARUS menghasilkan tepat salah satu state lengkap: revision lama atau revision baru, bukan campuran. |
| QUA-016 | Tidak boleh ada koneksi DNS/HTTP/HTTPS/WebSocket keluar selama startup, setup, unlock, CRUD, import, backup, dan settings. Hanya koneksi incoming host/LAN serta navigasi URL oleh pengguna yang diizinkan. |
| QUA-017 | Build release HARUS menonaktifkan source map publik dan development endpoint; error UI tidak boleh menampilkan stack trace. |
| QUA-018 | Semua fixture rahasia test HARUS unik dan dipindai pada vault, backup, temp directory, config, dan log untuk membuktikan tidak ada plaintext tersisa. |

## 14. Use case

### UC-01 — Setup vault pertama

| Elemen | Spesifikasi |
|---|---|
| Aktor | Klien LAN pertama |
| Prasyarat | `setup_required=true`; data directory writable |
| Alur utama | Aktor membuka URL; membaca/menyetujui risiko; memilih bahasa; memasukkan master dan konfirmasi; melihat strength; memilih recovery; submit; server atomik membuat vault/envelope/session; UI menampilkan recovery satu kali bila dipilih; aktor mengonfirmasi penyimpanan; vault tampil. |
| Alternatif | Password kosong/tidak cocok ditolak; password lemah boleh lanjut setelah acknowledgement; setup balapan mendapat 409; kegagalan write tidak membuat vault parsial. |
| Pascakondisi | Vault revision 1, setup endpoint tertutup, satu sesi tab aktif, dan backup awal revision 1 sudah dibuat. |
| Requirement | SET-001–009, SEC-001–018, PRD-008–009 |

### UC-02 — Unlock, refresh, dan lock

| Elemen | Spesifikasi |
|---|---|
| Aktor | Pemilik vault |
| Prasyarat | Vault sudah disiapkan dan locked |
| Alur utama | Masukkan master; server membuka envelope; token masuk sessionStorage; ticket membuat WebSocket owner; refresh memakai token yang sama dan reconnect ≤10 detik; aktor memilih Lock; state/token dibersihkan. |
| Alternatif | Master salah mendapat error generik; duplicate tab harus unlock sendiri; restart/putus >10 detik mengakhiri sesi. |
| Pascakondisi | Saat locked tidak ada token valid; key/plaintext dibersihkan best-effort bila sesi terakhir. |
| Requirement | SES-001–012, API-008–010 |

### UC-03 — Membuat dan mengelola Credential

| Elemen | Spesifikasi |
|---|---|
| Aktor | Klien unlocked |
| Prasyarat | Sesi valid |
| Alur utama | Buat item; isi field/category/tag/custom field; simpan; cari/filter/sort; buka detail; edit dengan revision; server commit+backup; klien menerima result/event. |
| Alternatif | Validasi inline; write/backup gagal tanpa mutasi; stale revision menuju UC-06. |
| Pascakondisi | Payload dan backup terenkripsi pada revision baru. |
| Requirement | CRD-001–020, BAK-001–006, UIX-001–010 |

### UC-04 — Reveal, copy, dan generator

| Elemen | Spesifikasi |
|---|---|
| Aktor | Klien unlocked |
| Alur utama | Secret awal masked; aktor reveal atau copy; copy memakai Clipboard API/fallback; aktor dapat meminta password generator dan menyimpan hasil. |
| Alternatif | Clipboard diblokir menampilkan dialog manual-copy; charset kosong/length invalid ditolak. |
| Pascakondisi | Reveal hanya state tab; clipboard tidak auto-clear; hasil generator tidak disimpan sampai save. |
| Requirement | CRD-005–007, GEN-001–005, UIX-011 |

### UC-05 — Trash dan aksi massal

| Elemen | Spesifikasi |
|---|---|
| Aktor | Klien unlocked |
| Alur utama | Pilih satu/banyak item; konfirmasi scope; snapshot untuk aksi destruktif; pindah ke Trash/restore/purge atau ubah metadata; transaksi atomik dan broadcast. |
| Alternatif | Item stale membatalkan seluruh batch; snapshot gagal membatalkan aksi; purge otomatis berjalan saat jatuh tempo. |
| Pascakondisi | Revision konsisten dan maksimal 30 hari untuk item Trash yang tidak direstore. |
| Requirement | TRS-001–007 |

### UC-06 — Sinkronisasi dan konflik edit

| Elemen | Spesifikasi |
|---|---|
| Aktor | Dua klien unlocked |
| Alur utama | Klien A menyimpan N→N+1; B menerima event ≤1 detik dan refetch. Jika B masih mengedit N, save ditolak; B memilih reload atau overwrite eksplisit berdasarkan revision terbaru. |
| Alternatif | WebSocket reconnect dengan gap memicu full reload data; event tidak membawa secret. |
| Pascakondisi | Tidak ada lost update diam-diam. |
| Requirement | CRD-009–010, API-011–016 |

### UC-07 — Impor CSV

| Elemen | Spesifikasi |
|---|---|
| Aktor | Klien unlocked |
| Alur utama | Pilih generic/Chromium/Firefox; upload; atur delimiter/mapping; tinjau valid/error/duplicate; pilih Skip/Update/Keep Both; download report bila perlu; commit valid rows atomik. |
| Alternatif | Encoding/ukuran salah ditolak; invalid rows dikecualikan; vault berubah sejak preview meminta preview baru. |
| Pascakondisi | Hanya pilihan valid ter-commit dan raw preview dibuang. |
| Requirement | IMP-001–016 |

### UC-08 — Ekspor plaintext

| Elemen | Spesifikasi |
|---|---|
| Aktor | Klien unlocked |
| Alur utama | Pilih profile/scope; baca peringatan; masukkan ulang master; server menghitung scope dan streaming CSV langsung; browser menyimpan download. |
| Alternatif | Master salah menolak tanpa output; stream gagal tidak meninggalkan temp file host. |
| Pascakondisi | Vault tidak berubah; CSV plaintext berada di perangkat klien dan menjadi tanggung jawab pengguna. |
| Requirement | EXP-001–010 |

### UC-09 — Backup dan restore

| Elemen | Spesifikasi |
|---|---|
| Aktor | Klien unlocked |
| Alur utama | Lihat manifest; buat/download backup; pilih backup terindeks/upload; server validasi; buat pre-restore; buka kandidat; atomic replace; seluruh sesi invalid dan client reload. |
| Alternatif | Checksum/AEAD/schema/key salah ditolak tanpa mengubah vault; disk failure mempertahankan vault lama. |
| Pascakondisi | Vault sama dengan revision snapshot terpilih dan harus di-unlock ulang. |
| Requirement | BAK-001–012 |

### UC-10 — Mengelola master dan recovery

| Elemen | Spesifikasi |
|---|---|
| Aktor | Klien unlocked atau pemilik locked dengan recovery key |
| Alur utama | Ganti master dengan lama+baru hanya rewrap DEK; atau enable/rotate/disable recovery dari settings; pada kehilangan master, masukkan recovery dan master baru lalu terima recovery baru. |
| Alternatif | Key/checksum salah ditolak; recovery tidak tersedia menampilkan data tidak dapat dipulihkan. |
| Pascakondisi | DEK/payload tetap, wrap aktif sesuai pilihan, key lama tidak berlaku setelah rotate/recovery. |
| Requirement | BAK-014, SEC-005–018 |

### UC-11 — Reset vault

| Elemen | Spesifikasi |
|---|---|
| Aktor | Klien unlocked |
| Alur utama | Buka danger zone; masukkan master saat ini, frasa, master baru, opsi recovery; server membuat pre-reset snapshot dan vault kosong baru; semua sesi invalid; recovery baru tampil sekali setelah unlock/setup result khusus. |
| Alternatif | Verifikasi/snapshot gagal membatalkan reset. |
| Pascakondisi | Setup endpoint tetap tertutup; vault lama hanya ada dalam backup terenkripsi. |
| Requirement | SET-007, BAK-009, BAK-013, SES-013 |

### UC-12 — Mengoperasikan launcher

| Elemen | Spesifikasi |
|---|---|
| Aktor | Pengguna host |
| Alur utama | Jalankan launcher; startup checks; tray ready; buka local URL/salin LAN URL; opsional autostart; lock-all; stop tertib. |
| Alternatif | Data tidak writable, instance/port bentrok, atau korupsi menghasilkan safe error dan log location. |
| Pascakondisi | Saat stop, server mati, OS lock dilepas, dan sesi tidak dapat dipakai ulang. |
| Requirement | PRD-005–013, OPS-001–013 |

## 15. Acceptance criteria dan strategi verifikasi

### 15.1 Aturan penerimaan

- Seluruh test di bawah HARUS otomatis kecuali yang diberi label `manual-assisted` untuk tray, visual, atau mesin fisik.
- Test menggunakan fake clock dan deterministic fault injection bila waktu, power loss, write failure, atau race sulit direproduksi.
- Tidak ada defect Severity 1/2 terbuka. Defect keamanan yang dapat mengekspos plaintext, menerima ciphertext tidak autentik, melewati reautentikasi, atau menyebabkan lost update adalah release blocker.
- Artefak yang diuji HARUS sama byte-for-byte dengan artefak release; hash dicatat di test report.

### 15.2 Setup, kriptografi, dan penyimpanan

| ID | Given / When | Then / kriteria lulus |
|---|---|---|
| AT-SEC-01 | Direktori baru; setup dengan master nonkosong dan recovery aktif | Vault dapat di-unlock; recovery tampil satu kali; setup kedua termasuk race 20 request menghasilkan satu `201` dan 19 `409`; tidak ada bootstrap code. |
| AT-SEC-02 | Password kosong, mismatch, dan password lemah | Kosong/mismatch ditolak; lemah menampilkan strength warning tetapi berhasil hanya setelah acknowledgement. Tidak ada batas komposisi; input Unicode panjang dalam batas request berhasil. |
| AT-SEC-03 | Envelope valid; coba master salah, recovery salah, checksum recovery salah | Semua ditolak tanpa sesi dan tanpa membedakan sumber kegagalan pada response/log. Tidak ada throttling/lockout setelah 100 kegagalan; master benar berikutnya langsung berhasil. |
| AT-SEC-04 | Fixture envelope; balik satu bit bergantian pada wrapped DEK, payload ciphertext, tag, nonce, vault ID, schema version, dan revision | Setiap kandidat gagal autentikasi/validasi dan tidak pernah menghasilkan plaintext atau mengganti vault aktif. |
| AT-SEC-05 | Instrumentasi CSPRNG production adapter pada 100.000 enkripsi payload/wrap | Seluruh nonce 96-bit untuk key yang sama unik, panjang benar, dan generator hanya memakai sumber OS; test juga membuktikan nonce aktif yang disuntik ulang ditolak. |
| AT-SEC-06 | Vault berisi marker secret; ganti master | DEK logical sama, payload ciphertext+nonce byte-identik, salt/wrapped master/nonce berubah; master lama gagal, baru berhasil. |
| AT-SEC-07 | Recovery aktif | Recovery mengganti master, menghasilkan recovery baru, dan memulihkan seluruh data; master/key lama gagal; enable/rotate/disable berperilaku sesuai SEC-015–018. |
| AT-SEC-08 | Vault dengan marker unik pada name, URL, username, password, tag, notes, history, dan custom fields; jalankan CRUD, backup, import invalid, export, dan lock | Pemindaian raw bytes/strings terhadap PostgreSQL, semua `.lvbak`, config, log, crash report terkendali, dan temp directory tidak menemukan marker. CSV download client dikecualikan dan diverifikasi tidak pernah ada sebagai host temp file. |
| AT-SEC-09 | Capture seluruh response API dan static headers | Semua API `no-store`; CSP/origin/Host rules aktif; CORS origin asing ditolak; token/query/body sensitif di-redact; tidak ada service worker/CDN/source map release. |
| AT-SEC-10 | Lock sesi terakhir, lock-all, restore, reset, dan shutdown dengan instrumented secret buffers | Cache/domain state dan reference key dilepas serta mutable buffer di-zeroize best-effort; dokumentasi test tidak mengklaim eliminasi dari GC/swap. |

### 15.3 CRUD, pencarian, history, dan Trash

| ID | Given / When | Then / kriteria lulus |
|---|---|---|
| AT-CRUD-01 | Dataset kombinatorial field wajib/opsional | Create/read/update menghasilkan UUID/timestamp/revision valid, field Unicode round-trip, dan invalid limit/reference ditolak atomik. |
| AT-CRUD-02 | Credential dengan Category, banyak tag, favorite, Text/Secret custom fields | CRUD, rename/merge/delete category/tag, favorite, masking, reveal, dan copy cocok dengan CRD-004–016; custom Secret masked kembali setelah sesi berakhir. |
| AT-CRUD-03 | Ubah password enam kali dan ubah field lain dua kali | History berisi tepat lima password sebelumnya dengan urutan/timestamp benar; perubahan non-password tidak menambah history; semuanya encrypted at rest. |
| AT-CRUD-04 | 1.000 fixture dengan variasi teks/case/Unicode | Search hanya mencakup field CRD-017; category/tag/favorite/status/field-presence filter, tag AND/OR, seluruh sort naik/turun, dan UUID tie-break menghasilkan expected golden set. |
| AT-CRUD-05 | Dua client membaca revision sama dan menyimpan perubahan berbeda | Save pertama berhasil; kedua `409` tanpa secret; reload membuang edit lokal setelah konfirmasi; overwrite eksplisit mempertahankan edit pilihan pengguna dan membuat revision berikutnya. |
| AT-TRS-01 | Soft delete dengan fake clock hari 0, 29:23:59:59, dan 30 | Item tersembunyi dari aktif, dapat direstore sebelum jatuh tempo, dan dipurge saat ≥30 hari pada startup/scheduler. |
| AT-TRS-02 | Batch 100 item dengan satu revision stale | Tidak ada item berubah. Setelah revision benar, tag/category/favorite/trash/restore berhasil atomik. Destructive batch membuat pre-operation snapshot lebih dahulu. |
| AT-TRS-03 | Empty Trash dengan count stale lalu benar | Count stale ditolak tanpa perubahan; count benar + confirmation membuat snapshot dan purge semua atomik. |
| AT-GEN-01 | Setiap kombinasi charset, boundary 4/256, exclude ambiguous, dan 100.000 sampel | Hasil memakai charset yang tepat, memenuhi set terpilih jika panjang cukup, tidak menunjukkan modulo bias pada statistical smoke threshold yang ditetapkan test, dan tidak muncul di log/payload sebelum save. |

### 15.4 Sesi dan realtime

| ID | Given / When | Then / kriteria lulus |
|---|---|---|
| AT-SES-01 | Satu tab unlocked | Refresh normal dan hard refresh reconnect <10 detik tetap unlocked dengan token sessionStorage yang sama; localStorage/cookie/IndexedDB kosong. |
| AT-SES-02 | Tab unlocked lalu ditutup | WebSocket putus dan token server invalid paling lambat 10 detik; memakai token hasil capture setelah itu mendapat 401. |
| AT-SES-03 | Duplikasikan tab dan buka URL pada tab/perangkat baru | Token hasil clone tidak dapat dimiliki kedua tab; tab baru meminta unlock; token berbeda dapat aktif bersamaan. |
| AT-SES-04 | Beberapa sesi aktif | Lock manual hanya mengakhiri tab itu; tray/API lock-all mengakhiri semua; restart server membatalkan semua token. Tidak ada sesi kembali tanpa unlock. |
| AT-SES-05 | Disconnect 5 detik lalu reconnect, serta disconnect >10 detik | Kasus pertama melanjutkan sesi/event; kasus kedua locked. Heartbeat aktif tidak menyebabkan idle/absolute timeout dalam endurance test 24 jam. |
| AT-SES-06 | 3 klien melakukan mutation berurutan/bersamaan | Semua menerima event non-rahasia dalam target; revision total order; gap/reconnect mengirim reload_required dan refetch memperoleh state final. |

### 15.5 CSV

Fixture wajib disimpan di test suite dan tidak berisi credential nyata:

- `excel-id-comma-utf8.csv`, `excel-id-semicolon-bom.csv`, dan `excel-tab.csv`;
- quoted comma/semicolon/tab, escaped quote, CRLF/LF, dan embedded newline;
- custom columns Text/Secret, Unicode Indonesia, baris kosong, invalid encoding, invalid row, serta 50 MiB/100.000-row boundary;
- hasil ekspor Chrome, Edge, Brave, dan Firefox dari versi exact release matrix.

| ID | Given / When | Then / kriteria lulus |
|---|---|---|
| AT-CSV-01 | Semua fixture generic Excel lokal Indonesia | Delimiter/BOM/quote/newline dideteksi; mapping standard/custom dan preview 100 baris benar; invalid row tidak mencegah commit valid row. |
| AT-CSV-02 | Fixture Chromium/Edge/Brave/Firefox | Preset memetakan field sesuai IMP-008–010; unknown columns hanya warning; fixture turunan Chromium harus lulus sebelum label kompatibel dirilis. |
| AT-CSV-03 | Data dengan pasangan URL/username ekivalen menurut normalisasi | Konflik terdeteksi tepat; default Skip; per-item/batch Skip/Update/Keep Both memberi golden result dan history benar. |
| AT-CSV-04 | Preview dibuat lalu vault bermutasi/preview expired/session lock | Commit ditolak, raw parsed values dibersihkan, dan pengguna diminta preview ulang. |
| AT-CSV-05 | Ekspor setiap profile dan scope lalu impor kembali ke target/profile yang sama | Spreadsheet round-trip mempertahankan seluruh field yang didefinisikan; profile browser cocok header/encoding dan mempertahankan subset yang didukung. CSV membuka benar di Excel locale Indonesia dan browser fixture import test. |
| AT-CSV-06 | Ekspor dengan master salah/benar dan field formula | Salah menghasilkan 401 tanpa bytes; benar streaming dengan header no-store tanpa file host; spreadsheet memitigasi formula, profile browser mempertahankan kompatibilitas dan warning. |
| AT-CSV-07 | Preview dengan baris invalid berisi marker secret | Download error report hanya memuat row number/code/message dan tidak memuat nilai sumber atau marker. |

### 15.6 Backup, restore, migrasi, dan failure injection

| ID | Given / When | Then / kriteria lulus |
|---|---|---|
| AT-BAK-01 | 25 mutasi pada satu hari dan proses aktif/startup melintasi 45 hari dengan fake clock | Backup ada setelah tiap mutasi sebelum response; tepat satu daily per hari aktif; retensi akhir adalah union 10 versi terbaru + satu daily per 30 tanggal UTC terbaru, tanpa menghapus file yang masuk kedua bucket. |
| AT-BAK-02 | Restore backup masing-masing revision lama, manual, dan uploaded dengan DEK sesi aktif untuk vault yang sama atau key historis untuk kandidat lain | Checksum/AEAD/schema/reference tervalidasi; state tepat sama snapshot; session invalid/reload; unlock ulang berhasil; UI tidak meminta reautentikasi untuk DEK aktif dan memperingatkan kebutuhan key historis sebelum rotasi. |
| AT-BAK-03 | Potong file, balik bit manifest/envelope, gunakan key salah, schema future, atau referensi entity invalid | Restore ditolak sebelum replace dan vault aktif byte-identik. |
| AT-BAK-04 | Suntik disk-full/permission/I/O failure pada setiap write, flush, rename, index, dan PostgreSQL commit | Sebelum commit menghasilkan revision lama dan error terarah; tidak ada response sukses tanpa backup wajib; orphan aman dibersihkan; tidak ada state campuran. |
| AT-BAK-05 | Kill proses pada setiap checkpoint mutation dan restore | Startup recovery memilih tepat state lengkap lama/baru dan integrity/AEAD check lulus, memenuhi QUA-015. |
| AT-BAK-06 | Jalankan schema migration dari setiap versi yang didukung dan paksa gagal tiap langkah | Snapshot pre-migration dibuat; sukses menghasilkan schema/data golden; gagal rollback ke versi lama yang dapat dibuka. |
| AT-BAK-07 | Ganti executable aplikasi dengan build baru sementara data folder tetap | Seluruh data, backup, config, dan recovery ability tetap utuh; aplikasi tidak menimpa data selain migrasi terkontrol. |

### 15.7 UI, kompatibilitas, packaging, dan performa

| ID | Given / When | Then / kriteria lulus |
|---|---|---|
| AT-UI-01 | Jalankan visual/interaction suite pada 360×800, 768×1024, 1440×900, zoom 100/200%, light/dark | Layout sesuai breakpoint, tidak ada inaccessible control/overflow, tabel/detail/list dan seluruh state UIX-018 berfungsi tanpa reload. |
| AT-UI-02 | Keyboard-only dan screen reader smoke pada setup, vault, detail, dialog, import/export/settings | Urutan/fokus/shortcut/live region/label benar; reveal state tidak diumumkan sebagai secret; automated axe-equivalent tidak menemukan pelanggaran serious/critical. |
| AT-UI-03 | Audit contrast dan target size | Seluruh warna/state light/dark memenuhi QUA-011–014 termasuk focus visible dan reduced motion. |
| AT-UI-04 | Ubah `id↔en` di setiap layar dan jalankan missing-key test | Semua teks berubah tanpa reload, default Indonesia, timestamp locale benar, tidak ada key mentah atau layout terpotong tanpa akses full text. |
| AT-UI-05 | Test matrix browser versi exact | Dua stable terbaru Chrome/Edge/Firefox dan Safari terbaru lulus CRUD, copy native/fallback/manual, WebSocket, download/upload, responsive, dan keyboard suite. |
| AT-PKG-01 | Mesin/VM bersih tiap OS tanpa Python/Node | Portable app start ≤target, setup, tray semua menu dalam id/en, LAN access, autostart user-level, stop/restart, dan data directory behavior lulus. |
| AT-PKG-02 | Port dipakai, data read-only, filesystem tanpa lock/atomic rename, instance kedua, config/vault korup | Startup menolak aman dengan error/log action dan tidak membuat port/data/vault pengganti. |
| AT-PERF-01 | Dataset/perangkat referensi dan 100 runs | p95 search/filter/sort <200 ms, mutation <500 ms, p99 broadcast <1 s, unlock ≤5 s, memory <512 MiB, tanpa main-thread freeze >200 ms. |
| AT-PERF-02 | 20 cold launches per OS | Setiap endpoint ready + shell interaktif ≤5 detik; report mencatat median/p95/max. |
| AT-NET-01 | Jalankan seluruh workflow di network sandbox dengan DNS/egress monitor | Nol DNS atau koneksi keluar. Hanya socket listen/incoming LAN; klik URL eksplisit menghasilkan navigasi browser yang teridentifikasi sebagai aksi pengguna. |

## 16. Traceability matrix

| Requirement | Sumber tujuan/use case | Komponen utama | Acceptance test |
|---|---|---|---|
| PRD-001–004 | Scope, 2.3, UC-12 | Build pipeline, FastAPI, React SPA | AT-PKG-01, AT-UI-05 |
| PRD-005–013 | UC-12 | Launcher, startup, repository | AT-PKG-01–02, AT-BAK-07 |
| SET-001–009 | UC-01 | Setup API, crypto, SPA | AT-SEC-01–02 |
| SES-001–013 | UC-02, UC-06, UC-08, UC-11 | Session Manager, auth middleware | AT-SES-01–06, AT-CSV-06 |
| CRD-001–008 | UC-03, UC-04 | Vault Service, React SPA | AT-CRUD-01–02 |
| CRD-009–010 | UC-06 | Vault Service, Event Broker | AT-CRUD-05, AT-SES-06 |
| CRD-011–016 | UC-03, UC-05, UC-10 | Domain model | AT-CRUD-02–03, AT-TRS-02 |
| CRD-017–020 | UC-03 | In-memory Vault Index | AT-CRUD-04, AT-PERF-01 |
| GEN-001–005 | UC-04 | Generator/Crypto Adapter | AT-GEN-01 |
| TRS-001–007 | UC-05 | Vault Service, Backup Manager | AT-TRS-01–03 |
| IMP-001–017 | UC-07 | Import Service | AT-CSV-01–05, AT-CSV-07 |
| EXP-001–010 | UC-08 | Export Service, auth | AT-CSV-05–06, AT-SEC-08–09 |
| BAK-001–008 | UC-03, UC-09 | Backup Manager, Repository | AT-BAK-01–05 |
| BAK-009–015 | UC-09–11 | Backup Manager, Crypto, migration | AT-BAK-02–07, AT-SEC-06–07 |
| SEC-001–010 | UC-01, UC-10 | Crypto Adapter | AT-SEC-03–06, AT-SEC-08 |
| SEC-011–018 | UC-01, UC-10 | Recovery Service, Crypto Adapter | AT-SEC-01, AT-SEC-03, AT-SEC-07 |
| SEC-019–023 | Seluruh use case rahasia | Crypto, memory/cache policy | AT-SEC-08–10 |
| SEC-024–032 | Threat model, UC-12 | Middleware, SPA, logging | AT-SEC-09, AT-NET-01, AT-UI-01 |
| DAT-001–006 | UC-03, UC-06 | Domain serializer | AT-CRUD-01, AT-BAK-05–06 |
| Model 8.2–8.10 | Entity kontrak | Domain, Repository, Import/Backup | AT-CRUD-01–04, AT-CSV-01–05, AT-BAK-02–03 |
| API-001–008 | Semua REST use case | FastAPI Presentation | Contract test seluruh AT-SEC/CRUD/CSV/BAK |
| API-009–016 | UC-02, UC-06 | Session Manager, Event Broker | AT-SES-01–06, AT-PERF-01 |
| UIX-001–018 | UC-01–12 | React SPA | AT-UI-01–03, AT-UI-05 |
| I18N-001–006 | Seluruh UI | i18n bundle, formatter | AT-UI-04 |
| OPS-001–013 | UC-12 | Launcher/Tray, logging | AT-PKG-01–02, AT-SEC-08–09, AT-UI-04 |
| QUA-001–006 | Performance goals | Semua runtime component | AT-PERF-01–02 |
| QUA-007–010 | Compatibility goals | Browser/build pipeline | AT-UI-05, AT-PKG-01, AT-BAK-07 |
| QUA-011–014 | Accessibility goals | React SPA/design tokens | AT-UI-02–03 |
| QUA-015–018 | Reliability/privacy goals | Repository, build, network policy | AT-BAK-04–05, AT-NET-01, AT-SEC-08–09 |

Catatan: baris “Model 8.2–8.10” menunjuk schema entity normatif, sedangkan DAT-001–006 mengatur aturan lintas-entity.

### 16.1 Traceability sumber eksternal

| Keputusan | Requirement terkait | Dasar |
|---|---|---|
| Argon2id dan parameter tersimpan | SEC-005 | OWASP Password Storage; baseline LocalVault 64 MiB/t=3/p=1 adalah keputusan produk. |
| AES-GCM, CSPRNG, key separation | SEC-001–010 | OWASP Cryptographic Storage. |
| HTTP LAN bukan secure context yang dapat diandalkan; localhost pengecualian khusus | 2.5, SEC-030, CRD-007 | MDN Secure Contexts. |
| Clipboard API dapat dibatasi secure context/permission | CRD-006–007, AT-UI-05 | MDN Clipboard API. |
| Browser CSV adalah plaintext dan format diuji fixture | IMP-008–010, EXP-006–007 | Dokumentasi Chrome dan Firefox pada 1.5. |
| Paket mandiri dan build per target OS | PRD-003–004, 12.6 | Dokumentasi PyInstaller pada 1.5. |
| Aksesibilitas AA | QUA-011–014 | WCAG 2.2. |

## 17. Risiko dan mitigasi residual

| Risiko | Peluang/dampak | Mitigasi wajib | Risiko residual yang diterima |
|---|---|---|---|
| Penyadapan/MITM/injeksi pada HTTP LAN | Tinggi/Kritis | Banner permanen, same-origin/CSP, dokumentasi isolasi LAN | Tidak dapat dihilangkan tanpa HTTPS; keputusan v1 diterima. |
| Klien LAN mengambil setup pertama | Sedang/Kritis | Peringatan launcher/setup, setup atomik, anjurkan jalankan pertama di jaringan tepercaya | Tidak ada bootstrap protection pada v1. |
| Brute force online/master lemah | Tinggi/Tinggi | Strength indicator dan warning | Tidak ada throttle/lockout; keputusan v1 diterima. |
| Host, browser, keylogger, atau sesi unlocked terkompromi | Sedang/Kritis | Scope key in-memory, lock, CSP, no external assets | Secret tetap dapat dicuri oleh host/sesi yang terkompromi. |
| Master hilang tanpa recovery | Sedang/Kritis | Warning eksplisit dan backup terenkripsi | Data tidak dapat dipulihkan; diterima oleh pengguna. |
| Clipboard menyimpan secret | Tinggi/Sedang | Toast/peringatan setiap copy, manual-copy fallback | Tidak ada auto-clear pada v1. |
| Keterbatasan zeroization Python/JS/OS swap | Sedang/Tinggi | Buffer mutable dan cleanup best-effort, threat model jujur | Salinan memori residual mungkin ada. |
| Korupsi/power loss portable filesystem | Sedang/Tinggi | Self-test filesystem, transaction, fsync, atomic rename, snapshot, fault test | Kerusakan media fisik tetap mungkin; pengguna perlu backup eksternal manual. |
| Backup setiap mutasi memperlambat operasi/menambah write | Sedang/Sedang | Retensi union, staging terenkripsi, target p95, storage error eksplisit | Workload besar dapat melampaui target 1.000 item. |
| Variasi CSV browser berubah | Tinggi/Sedang | Fixture versi exact, parser toleran kolom ekstra, release matrix | Versi browser mendatang mungkin memerlukan update preset. |
| Perbedaan native packaging/tray/autostart | Sedang/Tinggi | Build dan clean-machine test per OS | Distribusi Linux di luar release matrix tidak dijamin. |
| Tab close tidak dapat diberitahukan secara pasti | Tinggi/Sedang | WebSocket ownership dan grace 10 detik | Token dapat hidup hingga 10 detik setelah tab tertutup. |
| Tabrakan nonce GCM acak | Sangat rendah/Kritis | CSPRNG 96-bit, reject nonce aktif, test uniqueness, key rotation saat reset | Probabilitas nonnol diterima dan dipantau; tidak memakai nonce dari clock. |

## 18. Definition of Done v1

LocalVault v1 dapat diterima hanya jika:

1. seluruh requirement Must dalam dokumen ini diimplementasikan atau memiliki revisi SRS yang disetujui;
2. seluruh acceptance test Bagian 15 lulus pada artefak release dan bukti test disimpan;
3. traceability requirement–test tidak memiliki baris tanpa verifikasi;
4. security review mengonfirmasi envelope encryption, session lifecycle, redaction, no-store, dan no-egress;
5. release matrix mencatat OS/browser/version/hash artefak yang benar-benar diuji;
6. dokumentasi pengguna mengulang batas threat model, backup/recovery, risiko CSV plaintext, HTTP LAN, dan prosedur upgrade tanpa menimpa data.

Tidak ada keputusan produk terbuka untuk implementasi v1. Perubahan algoritme, protokol transport, model sesi, retensi, format CSV, schema entity, atau scope fitur memerlukan perubahan versi dokumen ini dan migrasi/compatibility plan bila sudah ada data pengguna.
