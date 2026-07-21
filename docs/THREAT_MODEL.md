# Threat model LocalVault v1

LocalVault melindungi data saat tersimpan dengan AES-256-GCM dan membungkus DEK menggunakan KEK Argon2id. Token, DEK, dan payload plaintext hanya berada di memori proses/browser selama sesi aktif; zeroization bersifat best-effort karena Python, JavaScript, GC, dan swap OS dapat menyisakan salinan.

HTTP dan WebSocket LAN v1 tidak memakai TLS. Perangkat pada jalur jaringan dapat membaca atau mengubah master password, token, serta secret yang dibuka. Jalankan hanya pada LAN tepercaya, jangan port-forward `8741`, dan anggap host, browser, akun OS, serta clipboard sebagai trusted computing base.

Tidak ada cloud, telemetry, breach lookup, CDN, metadata URL, rate limit, lockout, atau auto-update. Setup pertama dapat diambil alih klien LAN lain bila host baru diekspos sebelum pemilik menyelesaikan setup; lakukan setup pertama pada jaringan tepercaya.

CSV export adalah plaintext. LocalVault men-stream hasil ke browser dan tidak membuat file CSV sementara di host, tetapi file hasil download tetap harus diamankan dan dihapus oleh pengguna.
