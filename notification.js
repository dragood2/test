(async () => {
    // notification.js — Envoyer une notification PS5 via le RCE
    // 
    // IMPORTANT: Sans kernel exploit, on ne peut PAS appeler
    // sceKernelSendNotificationRequest() directement depuis le JS (pas de syscall wrapper).
    // 
    // La notification est deja envoyee automatiquement par la ROP chain au moment
    // du commitRce() dans exploit.js (sceKernelSendNotificationRequest via ROP).
    //
    // Ce qu'on PEUT faire depuis remote.js / ce REPL:
    // - Modifier le titre de la page (visible dans l'UI PS5)
    // - Logger dans les marques (visibles dans les logs exploit)
    // - Modifier le DOM de la page en cours

    // Changer le titre de la fenetre PS5
    document.title = "PS5 RCE ACTIVE - " + new Date().toLocaleTimeString();
    
    // Modifier l'interface exploit
    try {
        const cap = document.getElementById("cap");
        if (cap) cap.textContent = "RCE ACTIVE - Remote JS OK";
        const status = document.getElementById("status");
        if (status) { status.textContent = "Remote JS Connected"; status.className = "ok"; }
    } catch(e) {}

    mark("NOTIF-TEST", "notification.js execute avec succes");
    
    return "notification.js OK";
})()
