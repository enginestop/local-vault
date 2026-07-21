# Recovery, backup, restore, dan upgrade

- Simpan recovery key di lokasi terpisah. Key hanya ditampilkan sekali dan key lama tidak berlaku setelah rotasi/recovery.
- Backup `.lvbak` tetap terenkripsi. Salin backup penting ke media lain; retensi lokal bukan pengganti backup eksternal.
- Restore memvalidasi container, checksum, AEAD, schema, dan struktur payload sebelum mengganti state aktif, lalu membatalkan semua sesi.
- Untuk upgrade portable, hentikan LocalVault, pertahankan folder `LocalVault-Data` tanpa perubahan, ganti hanya folder/executable aplikasi, lalu jalankan build baru. Jangan memindahkan data saat proses masih aktif.
- Jika config/vault korup atau data directory read-only, launcher berhenti aman. Jangan membuat vault pengganti; pulihkan izin atau restore backup yang telah diverifikasi.
