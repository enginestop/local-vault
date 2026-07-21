# LocalVault Bug Audit v1

Tanggal audit: 20 Juli 2026
Status: Temuan audit kedua, belum diperbaiki
Metode: Pemeriksaan read-only terhadap frontend React/TypeScript, backend FastAPI/Python, kontrak API, keamanan, penyimpanan, backup, import/export, dan UI responsif.

## Ringkasan

Audit kedua menemukan bug yang masih tersisa walaupun build dan 36 pengujian sebelumnya telah lulus. Cakupan tes saat ini belum menguji beberapa jalur penting seperti transaksi backup berulang, refresh ketika vault sudah unlocked, DNS rebinding, import preview ganda, dan validasi data saat update.

| Severity | Jumlah |
| --- | ---: |
| Critical | 4 |
| High | 10 |
| Medium | 10 |
| Low | 4 |
| Fitur belum berfungsi | 9 kelompok |

## Critical

### BUG-001: Validasi Host header tidak berfungsi

- Referensi: `backend/localvault/main.py:65-75`, `backend/localvault/main.py:133-139`
- Dampak: Risiko DNS rebinding terhadap server yang bind ke `0.0.0.0`.
- Detail: Middleware mendeteksi Host yang tidak diizinkan, tetapi hanya menjalankan `pass` dan tetap meneruskan request.
- Perbaikan: Tolak Host yang tidak diizinkan dengan HTTP 400/421 atau gunakan `TrustedHostMiddleware`. Bind ke loopback secara default kecuali mode LAN diaktifkan secara eksplisit.
- Tes yang dibutuhkan: Request API dengan Host loopback, Host yang dikonfigurasi, dan Host asing.

### BUG-002: SPA fallback berpotensi membaca file di luar direktori static

- Referensi: `backend/localvault/main.py:122-128`
- Dampak: Potensi disclosure source code, konfigurasi, atau file lokal melalui path traversal.
- Detail: `full_path` langsung digabungkan dengan `static_dir`, lalu file dikirim jika `os.path.isfile()` bernilai benar.
- Perbaikan: Serahkan semua asset kepada `StaticFiles` dan gunakan fallback hanya untuk `index.html`. Jika file tambahan harus dilayani, resolve path dan pastikan hasilnya tetap berada di dalam `static_dir`.
- Tes yang dibutuhkan: Path normal, `../`, encoded traversal, absolute path, dan trailing segments.

### BUG-003: Penulisan backup dapat meninggalkan transaksi SQLite terbuka

- Referensi: `backend/localvault/services/backup_manager.py:34-81`, `backend/localvault/api/routes_backups.py:27-36`, `backend/localvault/api/routes_categories.py:85-108`, `backend/localvault/api/routes_categories.py:161-220`
- Dampak: Mutasi berikutnya dapat gagal dengan `cannot start a transaction within a transaction` dan dikembalikan sebagai HTTP 507.
- Skenario:
  1. Buat manual backup.
  2. Lakukan mutasi kredensial berikutnya.
  3. `BEGIN IMMEDIATE` dapat gagal karena INSERT backup belum di-commit.
- Jalur lain yang terdampak: delete category, rename tag, dan delete tag.
- Perbaikan: Semua pemanggilan `write_backup()` harus berada di dalam `immediate_tx()`. Untuk operasi kategori/tag, gunakan parameter `pre_operation` pada `vault.mutate()` daripada menulis snapshot sebelum transaksi.
- Tes yang dibutuhkan: Manual backup lalu mutasi, delete category, rename/delete tag, serta pengecekan `conn.in_transaction` setelah setiap operasi.

### BUG-004: Retention backup dapat merusak transaksi dan konsistensi file/index

- Referensi: `backend/localvault/services/vault_service.py:329-333`, `backend/localvault/services/backup_manager.py:83-118`
- Dampak: Setelah jumlah backup melewati retention, mutasi berikutnya dapat gagal. Index dapat menunjuk file yang sudah dihapus.
- Detail: `apply_retention()` melakukan DELETE tanpa commit. `_delete_backup()` menghapus file sebelum transaksi database dipastikan berhasil.
- Perbaikan: Jalankan retention dalam transaksi tersendiri dan koordinasikan penghapusan database/file agar rollback tidak menghasilkan index yatim.
- Tes yang dibutuhkan: Lebih dari 10 mutation backup, lalu mutasi tambahan; pastikan semua index memiliki file dan koneksi tidak berada dalam transaksi.

## High

### BUG-005: Update invalid dapat membuat vault tidak bisa dibuka kembali

- Referensi: `backend/localvault/api/routes_credentials.py:41-52`, `backend/localvault/api/routes_credentials.py:196-228`, `backend/localvault/api/routes_categories.py:56-82`, `backend/localvault/domain/models.py:55-150`
- Dampak: Data invalid dapat dienkripsi dan disimpan, tetapi ditolak Pydantic saat unlock berikutnya.
- Contoh: Update nama kredensial menjadi kosong, notes terlalu panjang, jumlah tag berlebihan, custom field duplikat, atau nama kategori terlalu panjang.
- Penyebab: Assignment langsung ke model tidak menjalankan validasi ulang.
- Perbaikan: Bentuk model pengganti menggunakan `Credential.model_validate()`/`Category.model_validate()`, atau aktifkan `validate_assignment`. Konversi error Pydantic menjadi HTTP 422 sebelum data dienkripsi.
- Tes yang dibutuhkan: Setiap constraint update, diikuti lock dan unlock round-trip.

### BUG-006: Refresh saat vault sudah unlocked dapat menampilkan vault kosong

- Referensi: `src/App.tsx:117-133`
- Dampak: Data tidak pernah dimuat setelah refresh tertentu.
- Detail: Nilai awal `screen` sudah `app`. Efek load berjalan ketika `status` masih null dan berhenti. Saat status menjadi unlocked, `setScreen('app')` tidak mengubah state, sehingga efek yang hanya bergantung pada `screen` tidak berjalan lagi.
- Perbaikan: Gunakan boot/loading screen terpisah atau tambahkan dependency `status?.setup_completed` dan `status?.locked` dengan guard terhadap load ganda.
- Tes yang dibutuhkan: Refresh browser ketika backend masih unlocked dan token masih valid.

### BUG-007: Status global dianggap sebagai bukti autentikasi klien

- Referensi: `src/App.tsx:117-133`, `src/api.ts:127-140`, `backend/localvault/api/routes_status.py:25-43`
- Dampak: Tab tanpa token atau dengan token kedaluwarsa masuk ke layar aplikasi karena tab lain membuka vault, lalu semua request protected gagal 401.
- Perbaikan: Jika status menyatakan unlocked, validasi token lokal dengan `api.current()`. Jika gagal, hapus token dan tampilkan login.
- Tambahan: Simpan token/tab ID di `sessionStorage`, bukan satu token global di `localStorage`.
- Tes yang dibutuhkan: Dua tab, token hilang, token invalid, dan vault global unlocked.

### BUG-008: Tidak ada penanganan terpusat untuk sesi invalid

- Referensi: `src/api.ts:97-123`, `src/App.tsx:108-133`
- Dampak: UI tetap menampilkan connected/unlocked setelah sesi invalid atau vault dikunci dari klien lain.
- Perbaikan: Normalisasi `401 SESSION_INVALID` dan `423 VAULT_LOCKED` untuk membersihkan state/token dan kembali ke login. Jangan logout otomatis untuk `401 REAUTH_REQUIRED`.
- Tes yang dibutuhkan: Invalidate token selama aplikasi terbuka dan lock dari sesi lain.

### BUG-009: Recovery, change-master, dan reset menerima master password kosong

- Referensi: `backend/localvault/api/routes_settings.py:57-95`, `backend/localvault/api/routes_settings.py:173-229`, `backend/localvault/services/vault_service.py:241-294`, `src/App.tsx:368-369`, `src/App.tsx:458-461`
- Dampak: Vault dapat dikonfigurasi agar terbuka menggunakan password kosong.
- Perbaikan: Gunakan satu fungsi kebijakan password untuk setup, recovery, change-master, dan reset. Minimal tolak string kosong dan enforce acknowledgement untuk password lemah.
- Tes yang dibutuhkan: Password kosong, whitespace-only, confirmation mismatch, dan weak-password acknowledgement.

### BUG-010: Recovery key baru dibuang setelah recovery atau reset

- Referensi: `src/App.tsx:331-334`, `src/App.tsx:440`, `backend/localvault/api/routes_session.py:94-105`, `backend/localvault/api/routes_settings.py:203-229`
- Dampak: Key lama tidak berlaku setelah rotasi, sedangkan key baru tidak ditampilkan/disimpan. Pengguna kehilangan satu-satunya recovery key valid.
- Perbaikan: Tampilkan key baru dalam dialog wajib, sediakan copy/download, dan minta acknowledgement sebelum masuk atau reload.
- Tes yang dibutuhkan: Recovery dan reset menghasilkan key baru yang dapat digunakan setelah key lama ditolak.

### BUG-011: Session tab tidak pernah kedaluwarsa secara efektif

- Referensi: `backend/localvault/services/session_manager.py:99-155`, `backend/localvault/api/routes_events.py:64-76`
- Dampak: Menutup tab dapat meninggalkan token, DEK, dan plaintext vault hidup tanpa batas.
- Detail: `cleanup_expired()` tidak pernah dijalankan. Frontend juga tidak membuka event WebSocket.
- Perbaikan: Tambahkan scheduler cleanup, absolute/inactivity expiry, per-tab ID, dan lock vault ketika sesi terakhir hilang.
- Tes yang dibutuhkan: Disconnect tab, grace period, expiry, dan auto-lock setelah sesi terakhir.

### BUG-012: WebSocket tidak menerima event vault

- Referensi: `backend/localvault/services/session_manager.py:130-144`, `backend/localvault/api/routes_events.py:31-76`
- Dampak: `vault.changed` dan `vault.locked` tidak pernah mencapai klien.
- Detail: WebSocket menggunakan queue lokal melalui `set_ws_connected()`, tetapi `broadcast()` hanya menulis ke `_subscribers`. Queue WebSocket tidak pernah disubscribe.
- Perbaikan: Subscribe/unsubscribe queue WebSocket pada `SessionManager` atau broadcast langsung ke `owner_ws` setiap sesi.
- Tes yang dibutuhkan: Event perubahan vault, lock, reconnect, dan sync-state.

### BUG-013: Import preview kedua dapat menghasilkan HTTP 500

- Referensi: `backend/localvault/services/import_service.py:99-111`, `backend/localvault/api/routes_imports.py:26-81`
- Dampak: Membuat preview baru setelah preview pertama belum dikomit dapat gagal.
- Detail: `created_at` dan `expires_at` tetap string kosong. `_expire()` menjalankan `datetime.fromisoformat("")`.
- Perbaikan: Isi timestamp timezone-aware ketika preview dibuat dan tangani timestamp invalid secara defensif.
- Tes yang dibutuhkan: Dua preview berturut-turut, preview kedaluwarsa, dan preview invalid.

### BUG-014: Import update existing rusak ketika CSV memiliki kategori

- Referensi: `backend/localvault/api/routes_imports.py:245-247`, `backend/localvault/api/routes_imports.py:279-309`
- Dampak: Commit conflict resolution `update` dapat menghasilkan HTTP 500.
- Detail: `_apply_fields()` memanggil `_find_cat(t.__dict__ and None, ...)`, yang mengirim `None` lalu dereference `payload.categories`.
- Perbaikan: Kirim `VaultPayload` yang sebenarnya ke `_apply_fields()` dan update password history jika password berubah.
- Tes yang dibutuhkan: Import duplicate dengan resolution update, kategori existing, dan kategori baru.

## Medium

### BUG-015: Import preview tidak diikat ke sesi pemilik

- Referensi: `backend/localvault/api/routes_imports.py:70-73`, `backend/localvault/api/routes_imports.py:166-276`
- Dampak: Sesi lain yang mengetahui UUID preview dapat melihat, mengubah resolution, commit, atau cancel preview tersebut.
- Perbaikan: Bandingkan `preview.session_id` dengan sesi request pada semua endpoint preview. Lindungi seluruh akses store dengan `_PREVIEW_LOCK`.

### BUG-016: Validasi import preview lebih lemah daripada commit

- Referensi: `backend/localvault/api/routes_imports.py:125-132`, `backend/localvault/api/routes_imports.py:249-265`
- Dampak: Baris terlihat valid di preview tetapi commit gagal atau menghasilkan HTTP 500.
- Detail: Preview hanya memvalidasi nama, bukan notes, tag, custom fields, atau ukuran payload.
- Perbaikan: Bangun candidate `Credential` saat preview dan simpan error terstruktur. Tangani UTF-8/CSV/Pydantic error sebagai HTTP 422.

### BUG-017: Import/export LocalVault tidak dapat round-trip dengan aman

- Referensi: `backend/localvault/services/export_service.py:28-83`, `backend/localvault/api/routes_imports.py:112-122`
- Dampak: Formula-prefix apostrophe tidak dipulihkan dan custom fields/metadata dapat hilang.
- Perbaikan: Implementasikan preset `localvault` khusus yang membaca `_localvault_escape_map`, memulihkan prefix exporter, dan mem-parsing `custom_fields_json`.

### BUG-018: Generator exclude-ambiguous membuang character pool

- Referensi: `backend/localvault/crypto/password_gen.py:40-50`
- Dampak: Huruf kecil, huruf besar, dan angka dapat seluruhnya hilang dari hasil. Jika simbol tidak dipilih, request dapat gagal total.
- Detail: Pool dibuang jika memiliki minimal satu karakter ambigu, bukan hanya menghapus karakter ambigu tersebut.
- Perbaikan: Filter karakter ambigu dari setiap pool lalu buang hanya pool yang benar-benar kosong.
- Tes yang dibutuhkan: Semua kombinasi charset dengan `exclude_ambiguous=true` dan pemeriksaan representasi tiap kelas terpilih.

### BUG-019: Filtered export tidak merepresentasikan filter UI dan dapat mencakup Trash

- Referensi: `src/App.tsx:526-530`, `backend/localvault/api/routes_exports.py:45-56`
- Dampak: Pengguna memilih hasil filter saat ini tetapi mendapatkan data yang berbeda, termasuk kemungkinan item Trash.
- Perbaikan: Kirim query, category, tag, favorite, dan status aktif. Backend harus menggunakan filter yang sama dengan list endpoint serta memvalidasi enum scope.
- Tes yang dibutuhkan: Kombinasi query/category/tag/favorite/status dan item deleted.

### BUG-020: Frontend hanya memuat maksimal 500 kredensial

- Referensi: `src/App.tsx:108-113`, `backend/localvault/api/routes_credentials.py:111-121`
- Dampak: Item setelah 500 tidak dapat dicari, diedit, direstore, atau dihitung dengan benar. Empty Trash dapat gagal `COUNT_STALE`.
- Perbaikan: Implementasikan pagination UI atau fetch seluruh halaman sampai jumlah item sama dengan `total`.
- Tes yang dibutuhkan: Vault dengan 501+ item dan Trash melebihi satu halaman.

### BUG-021: Selection bar dapat menarget item tersembunyi setelah filter berubah

- Referensi: `src/App.tsx:242-285`
- Dampak: Bulk action dapat dijalankan terhadap item yang tidak lagi terlihat.
- Perbaikan: Clear atau intersect `selectedRows` ketika set ID hasil filter berubah. Hitung select-all dengan `filtered.every(...)`.

### BUG-022: Generator dapat menggunakan ulang password milik kredensial lain

- Referensi: `src/App.tsx:100`, `src/App.tsx:499-538`
- Dampak: Password generated untuk item A masih tampil saat membuka generator item B karena state generator bersifat global.
- Perbaikan: Scope state generator ke modal/credential atau reset `pw` saat modal new/edit dibuka. Regenerate ketika generator dibuka.

### BUG-023: Error API belum dinormalisasi menjadi string aman

- Referensi: `src/api.ts:97-123`, berbagai `catch` pada `src/App.tsx`
- Dampak: FastAPI validation `detail` dapat berupa array objek dan menyebabkan React mencoba merender object. Network error sering menghasilkan toast kosong.
- Perbaikan: Normalisasi validation arrays, body non-JSON, status text, dan `TypeError` network menjadi string sebelum membuat `ApiError`.

### BUG-024: Lock failure ditelan tetapi UI mengklaim vault terkunci

- Referensi: `src/App.tsx:247`
- Dampak: Jika backend tidak dapat dijangkau, token lokal dihapus dan login ditampilkan walaupun sesi backend mungkin masih hidup.
- Perbaikan: Pindah ke login hanya setelah lock dikonfirmasi. Jika gagal, tampilkan pesan bahwa server lock belum terkonfirmasi dan sediakan retry.

## Low

### BUG-025: Tag rename/delete tidak memperbarui revision kredensial

- Referensi: `backend/localvault/api/routes_categories.py:161-220`
- Dampak: Klien dengan revision lama dapat overwrite perubahan tag karena revision item tidak berubah.
- Tambahan: `X-Vault-Revision` pada rename diparsing tetapi tidak dibandingkan; delete hanya memeriksa keberadaan header.
- Perbaikan: Validasi exact vault revision dan increment `revision`/`updated_at` pada setiap kredensial terdampak.

### BUG-026: Bulk operation mengabaikan revision dan action invalid

- Referensi: `backend/localvault/api/routes_credentials.py:289-352`
- Dampak: Stale update tidak terdeteksi; action tidak dikenal tetap membuat vault revision/backup baru dan melaporkan sukses.
- Perbaikan: Gunakan typed request dengan enum action, validasi semua revision sebelum mutasi, dan update timestamp hanya jika data berubah.

### BUG-027: Category rename tidak menjaga uniqueness dan batas panjang

- Referensi: `backend/localvault/api/routes_categories.py:56-82`
- Dampak: Kategori duplikat atau invalid dapat disimpan dan berpotensi merusak unlock berikutnya.
- Perbaikan: Validasi model pengganti dan terapkan aturan NFKC-casefold yang sama seperti create.

### BUG-028: Nonce tracker menyimpan raw key tanpa batas

- Referensi: `backend/localvault/crypto/csprng.py:38-52`, `backend/localvault/services/vault_service.py:44`
- Dampak: DEK/KEK lama tertahan dalam memori dan set bertumbuh setiap mutasi. `forget_key()` tidak pernah dipanggil.
- Perbaikan: Hindari penyimpanan raw key global. Jika tracking tetap diperlukan, gunakan identifier bounded per active key dan bersihkan saat lock/rotation/reset.

## Backup Integrity dan Restore Hardening

### BUG-029: Metadata hash backup tidak konsisten dan tidak diverifikasi

- Referensi: `backend/localvault/services/backup_manager.py:34-50`, `backend/localvault/services/backup_manager.py:143-154`, `backend/localvault/domain/envelope.py:152-167`
- Detail: Hash dihitung dari container saat manifest masih memiliki hash kosong, lalu manifest diubah dan container dipack ulang. Parser tidak memverifikasi field tersebut.
- Perbaikan: Hash bagian non-self-referential seperti envelope bytes, lalu verifikasi container version, manifest/envelope consistency, truncation, dan trailing bytes.

### BUG-030: Restore tidak memvalidasi struktur VaultPayload

- Referensi: `backend/localvault/api/routes_backups.py:67-115`
- Dampak: Payload yang dapat didekripsi tetapi invalid secara struktur dapat menggantikan vault dan membuat unlock berikutnya gagal.
- Perbaikan: Setelah decrypt, jalankan `VaultPayload.model_validate_json()` dan validasi schema/format/KDF sebelum replacement transaction.

### BUG-031: Nama file backup dapat bertabrakan

- Referensi: `backend/localvault/services/backup_manager.py:35-53`
- Dampak: Dua backup dengan revision/kind sama pada milidetik yang sama dapat menulis file yang sama tetapi membuat dua index row.
- Perbaikan: Sertakan `backup_id` dalam nama file.

## Masalah UI dan Aksesibilitas

### BUG-032: Restore backup disembunyikan pada tablet/mobile

- Referensi: `src/App.tsx:424`, `src/styles.css:76-78`
- Dampak: Tombol restore terakhir disembunyikan tanpa alternatif pada ukuran tertentu.
- Perbaikan: Pertahankan tombol restore atau pindahkan ke overflow menu yang tetap dapat diakses.

### BUG-033: Modal dan mobile navigation tidak memiliki focus trap/inert

- Referensi: `src/App.tsx:217-236`, `src/App.tsx:483-512`, `src/styles.css:80-82`
- Dampak: Keyboard dapat fokus ke konten belakang dialog atau sidebar yang sedang off-screen.
- Perbaikan: Gunakan dialog/focus-trap yang teruji, set background `inert`, sembunyikan nav tertutup dari accessibility tree, dan restore focus saat close.

### BUG-034: Mode English masih berisi banyak teks Indonesia

- Referensi: Banyak hardcoded string pada `src/App.tsx`; dictionary di `src/i18n.ts` belum mencakup seluruh teks/ARIA/error.
- Dampak: UI dan screen reader menggunakan campuran bahasa.
- Perbaikan: Pindahkan seluruh teks user-facing, aria-label, error, confirm, toast, dan pluralization ke dictionary.

### BUG-035: Timeout toast lama dapat menghapus toast baru

- Referensi: `src/App.tsx:105`
- Dampak: Pesan terbaru dapat hilang lebih cepat karena timeout dari pesan sebelumnya.
- Perbaikan: Simpan timeout ID dan cancel timeout sebelumnya sebelum menjadwalkan yang baru.

### BUG-036: Export modal selalu menutup setelah error

- Referensi: `src/App.tsx:526`
- Dampak: Salah master password memaksa pengguna membuka ulang modal dan mengisi ulang konfigurasi.
- Perbaikan: Tutup modal hanya setelah download berhasil.

### BUG-037: Object URL export tidak dibersihkan

- Referensi: `src/App.tsx:526`
- Dampak: Export berulang menyebabkan object URL tetap hidup sampai halaman ditutup.
- Perbaikan: Panggil `URL.revokeObjectURL()` setelah klik download dan gunakan filename dari `Content-Disposition` atau profil yang dipilih.

### BUG-038: Settings load error ditelan

- Referensi: `src/App.tsx:437`
- Dampak: Bagian settings menghilang tanpa pesan ketika request gagal.
- Perbaikan: Tambahkan loading/error state, retry, dan integrasikan invalid-session handling.

### BUG-039: Destructive action kurang confirmation/pending protection

- Referensi: `src/App.tsx:257`, `src/App.tsx:276`, `src/App.tsx:409-410`
- Dampak: Empty Trash dan permanent purge dapat terpicu tidak sengaja atau diklik ganda.
- Perbaikan: Tambahkan confirmation yang menyebut jumlah/nama item serta disable kontrol selama request.

## Import UI Contract

### BUG-040: Kontrol import frontend tidak sesuai dengan backend

- Referensi: `src/App.tsx:546-568`, `src/api.ts:217-225`, `backend/localvault/api/routes_imports.py:45-122`
- Masalah:
  - Profile `auto` tidak benar-benar dideteksi backend.
  - Dropdown delimiter tidak memiliki state dan nilainya tidak dikirim.
  - Firefox CSV dapat tidak memiliki field `name` yang diwajibkan.
  - Conflict default ke `skip`, tetapi UI tidak menyediakan resolution control.
- Perbaikan: Selaraskan enum profile, kirim delimiter/mapping, synthesize nama Firefox secara aman, dan tambahkan UI conflict resolution.

## Perilaku dan Konfigurasi Tambahan

### BUG-041: Language setting vault tidak dipakai saat boot

- Referensi: `src/App.tsx:79`, `src/App.tsx:437-452`
- Dampak: Browser baru tetap menggunakan Indonesia walaupun vault disimpan dengan English. Local storage dapat berbeda dari vault jika save gagal.
- Perbaikan: Setelah autentikasi, inisialisasi bahasa dari `api.general().language` dan persist local storage hanya setelah save sukses.

### BUG-042: Tag mode tidak efektif untuk satu parameter tag

- Referensi: `backend/localvault/api/routes_credentials.py:64-104`
- Dampak: Cabang AND dan OR menghasilkan kondisi yang sama.
- Perbaikan: Terima list/repeated tags dan implementasikan `all()` vs `any()`.

### BUG-043: Timestamp helper memanggil waktu dua kali

- Referensi: `backend/localvault/domain/models.py:18-21`, helper serupa di `session_manager.py`, `backup_manager.py`, dan `routes_events.py`.
- Dampak: Pada batas detik, bagian detik dan milidetik dapat berasal dari instant berbeda.
- Perbaikan: Simpan `now = datetime.now(timezone.utc)` sekali lalu format objek tersebut.

### BUG-044: Konfigurasi Vite duplikat

- Referensi: `vite.config.ts`, `vite.config.js`, `tsconfig.node.json`
- Dampak: Developer dapat mengedit TS tetapi runtime menggunakan JS lama jika keduanya berbeda.
- Perbaikan: Pertahankan satu file konfigurasi authored dan cegah TypeScript menghasilkan sibling config runtime.

### BUG-045: Dependency menggunakan `latest`

- Referensi: `package.json:11-21`
- Dampak: Regenerasi lockfile dapat menarik major version yang tidak kompatibel.
- Perbaikan: Gunakan range versi eksplisit dan pindahkan build tooling ke `devDependencies`.

## Fitur Belum Berfungsi atau Masih Placeholder

Bagian berikut bukan sekadar edge-case, tetapi kontrol UI yang belum mempunyai implementasi nyata:

1. Notification, Help, dan Profile: `src/App.tsx:245-248`.
2. Row overflow menu: `src/App.tsx:293`.
3. Link URL kredensial mencegah navigasi dan hanya menampilkan toast: `src/App.tsx:396`.
4. Detail menu dan password history: `src/App.tsx:394-405`.
5. Download backup dan restore dari file: `src/App.tsx:424-426`.
6. Navigasi subsection Settings: `src/App.tsx:444-446`.
7. Rename/delete category belum tersedia di UI walaupun API client ada.
8. Import conflict resolution dan mapping belum tersedia.
9. Direct generator dari detail membuka edit form, bukan langsung generator.

## Prioritas Perbaikan

Urutan implementasi yang direkomendasikan:

1. BUG-001 sampai BUG-004: keamanan Host/path dan transaksi backup.
2. BUG-005 sampai BUG-010: integritas vault, boot auth, password, dan recovery key.
3. BUG-011 sampai BUG-018: session/WebSocket, import, dan generator.
4. BUG-019 sampai BUG-024: export, pagination, selection, error handling, dan lock semantics.
5. BUG-025 sampai BUG-031: revision, bulk validation, nonce, dan backup integrity.
6. BUG-032 sampai BUG-045: responsivitas, aksesibilitas, localization, UX, dan konfigurasi.
7. Implementasikan seluruh kontrol placeholder dan tambahkan regression test untuk setiap jalur.

## Catatan Verifikasi

- Dokumen ini berasal dari audit read-only kedua.
- Tidak ada file source yang diubah saat audit tersebut.
- Build dan 36 test yang sebelumnya lulus tidak membuktikan jalur di atas bebas bug karena banyak skenario belum tercakup.
- Beberapa temuan keamanan seperti encoded traversal tetap perlu dibuktikan dengan integration test raw HTTP setelah perbaikan dirancang.
