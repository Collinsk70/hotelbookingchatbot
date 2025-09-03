// Hotel Booking Chatbot :
//  - keeps a live/replaceable summary (top) that updates as the user edits
//  - when a booking is confirmed, appends a final summary immediately after the confirmation reply
//  - final summary is distinct from the live summary so users see the confirmation then the summary

(async () => {
  const chatEl = document.getElementById("chat");
  const form = document.getElementById("inputForm");
  const input = document.getElementById("messageInput");

  const DEFAULT_PLACEHOLDER = "Say something like 'Book a room for 2 from May 2 to May 5'...";

  let session_id = localStorage.getItem("hc_session");
  if (!session_id) {
    const r = await fetch("/api/session", { method: "POST" });
    const j = await r.json();
    session_id = j.session_id;
    localStorage.setItem("hc_session", session_id);
  }

  function appendBubble(text, who = "bot", small = false) {
    const b = document.createElement("div");
    b.className = `msg ${who}`;
    if (small) b.classList.add("small");
    b.innerText = text;
    chatEl.appendChild(b);
    chatEl.scrollTop = chatEl.scrollHeight;
    return b;
  }

  // Replaceable live summary (uses data-booking-id)
  function appendOrReplaceLiveSummary(summary) {
    if (!summary) return;
    const idStr = String((typeof summary.id !== "undefined" && summary.id !== null) ? summary.id : (summary.session_id || "booking"));
    const selector = `[data-booking-id="${idStr}"]`;
    const existing = chatEl.querySelector(selector);

    const s = document.createElement("div");
    s.className = "msg bot summary";
    s.setAttribute("data-booking-id", idStr);

    s.innerHTML = `
      <strong>Booking summary</strong><br/>
      Name: ${summary.guest_name || '-'}<br/>
      Check-in: ${summary.checkin ? new Date(summary.checkin).toLocaleString() : '-'}<br/>
      Check-out: ${summary.checkout ? new Date(summary.checkout).toLocaleString() : '-'}<br/>
      Nights: ${summary.nights || '-'}<br/>
      Guests: ${summary.guests || '-'}<br/>
      Breakfast: ${summary.breakfast || '-'}<br/>
      Payment: ${summary.payment_method || '-'}<br/>
      Confirmed: ${summary.confirmed ? 'Yes' : 'No'}
    `;

    if (existing) {
      existing.replaceWith(s);
    } else {
      // insert near the top of the chat so it behaves like a persistent summary
      // put after header greeting if present; otherwise just append
      const firstBotMsg = chatEl.querySelector(".msg.bot");
      if (firstBotMsg) {
        firstBotMsg.insertAdjacentElement("afterend", s);
      } else {
        chatEl.appendChild(s);
      }
    }
    chatEl.scrollTop = chatEl.scrollHeight;
  }

  // Final summary appended after the confirmation reply (distinct element)
  function appendOrReplaceFinalSummary(summary) {
    if (!summary) return;
    const idStr = String((typeof summary.id !== "undefined" && summary.id !== null) ? summary.id : (summary.session_id || "booking"));
    const finalSelector = `[data-booking-id-final="${idStr}"]`;
    const existingFinal = chatEl.querySelector(finalSelector);

    const s = document.createElement("div");
    s.className = "msg bot summary final-summary";
    s.setAttribute("data-booking-id-final", idStr);

    s.innerHTML = `
      <strong>Final booking summary</strong><br/>
      Name: ${summary.guest_name || '-'}<br/>
      Check-in: ${summary.checkin ? new Date(summary.checkin).toLocaleString() : '-'}<br/>
      Check-out: ${summary.checkout ? new Date(summary.checkout).toLocaleString() : '-'}<br/>
      Nights: ${summary.nights || '-'}<br/>
      Guests: ${summary.guests || '-'}<br/>
      Breakfast: ${summary.breakfast || '-'}<br/>
      Payment: ${summary.payment_method || '-'}<br/>
      Confirmed: ${summary.confirmed ? 'Yes' : 'No'}
    `;

    if (existingFinal) {
      existingFinal.replaceWith(s);
    } else {
      // append at the bottom (immediately after whatever was just appended, typically the confirmation reply)
      chatEl.appendChild(s);
    }
    chatEl.scrollTop = chatEl.scrollHeight;
  }

  function appendProgress(booking) {
    const p = document.createElement("div");
    p.className = "msg bot small";
    const missing = computeMissing(booking);
    p.innerText = missing.length ? `Waiting for: ${missing.join(", ")}` : "All required fields are present.";
    chatEl.appendChild(p);
    chatEl.scrollTop = chatEl.scrollHeight;
  }

  function computeMissing(booking) {
    if (!booking) return ["name", "dates", "number of guests"];
    const missing = [];
    const hasName = Boolean(booking.guest_name && booking.guest_name.trim());
    const hasGuests = Boolean(booking.guests && Number(booking.guests) > 0);
    const hasDates = Boolean((booking.checkin && (booking.checkout || booking.nights)));
    if (!hasName) missing.push("name");
    if (!hasDates) missing.push("dates (check-in/check-out or nights)");
    if (!hasGuests) missing.push("number of guests");
    return missing;
  }

  function bookingHasAllRequired(booking) {
    if (!booking) return false;
    const missing = computeMissing(booking);
    return missing.length === 0;
  }

  function setContextualPlaceholder(booking) {
    const missing = computeMissing(booking);
    if (missing.length === 1) {
      const field = missing[0];
      if (field.includes("name")) input.placeholder = "Please enter the name for the reservation (e.g., John Smith)";
      else if (field.includes("dates")) input.placeholder = "Please enter dates (e.g., 'Aug 20 to Aug 25' or 'next Monday for 3 nights')";
      else if (field.includes("guests")) input.placeholder = "How many guests will stay? (e.g., 2)";
      else input.placeholder = DEFAULT_PLACEHOLDER;
    } else {
      input.placeholder = DEFAULT_PLACEHOLDER;
    }
  }

  async function sendMessage(text) {
    // user bubble
    appendBubble(text, "user");
    input.value = "";
    // temporary typing indicator
    appendBubble("...", "bot", true);

    try {
      const r = await fetch("/api/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id })
      });
      const j = await r.json();

      // debugging aid - see server JSON in browser console
      console.debug("Server response:", j);

      // Remove typing placeholders
      const placeholders = Array.from(chatEl.querySelectorAll(".msg.bot.small"));
      placeholders.forEach(p => p.remove());

      // Append server reply (always)
      if (j.reply) {
        appendBubble(j.reply, "bot");
      }

      const booking = j.booking || null;
      const serverFlag = (typeof j.all_required_present !== "undefined") ? Boolean(j.all_required_present) : null;

      if (booking) {
        // Update the live summary at top (replace or create)
        appendOrReplaceLiveSummary(booking);

        const confirmed = Boolean(
          booking.confirmed === true ||
          booking.confirmed === "True" ||
          booking.confirmed === "true" ||
          booking.confirmed === 1 ||
          booking.confirmed === "1"
        );

        // If the booking is confirmed, append a FINAL summary after the confirmation reply.
        // This ensures the user sees: "Thanks ... " followed by the final summary.
        if (confirmed) {
          appendOrReplaceFinalSummary(booking);
          input.placeholder = DEFAULT_PLACEHOLDER;
          return;
        }

        // If server says all_required_present but not confirmed, we keep live summary and invite confirm.
        if (serverFlag === true) {
          input.placeholder = DEFAULT_PLACEHOLDER;
          return;
        }

        // Otherwise show progress message + contextual placeholder
        appendProgress(booking);
        setContextualPlaceholder(booking);
        return;
      } else {
        input.placeholder = DEFAULT_PLACEHOLDER;
      }
    } catch (err) {
      const placeholders = Array.from(chatEl.querySelectorAll(".msg.bot.small"));
      placeholders.forEach(p => p.remove());
      appendBubble("Sorry — I couldn't reach the server. Try again.", "bot");
      console.error(err);
      input.placeholder = DEFAULT_PLACEHOLDER;
    }
  }

  // initial greeting
  appendBubble("Hello! I'm your hotel booking assistant. Tell me when you'd like to stay and for how many guests — I'll take care of the rest.", "bot");
  input.placeholder = DEFAULT_PLACEHOLDER;

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    sendMessage(text);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.dispatchEvent(new Event("submit"));
    }
  });
})();
