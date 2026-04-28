/** @odoo-module **/

function isApplePaySupported() {
    if (typeof window.ApplePaySession === "undefined") {
        return false;
    }
    if (typeof window.ApplePaySession.canMakePayments !== "function") {
        return false;
    }
    try {
        return window.ApplePaySession.canMakePayments();
    } catch {
        return false;
    }
}

function getApplePayRadios(rootElement) {
    const radios = rootElement.querySelectorAll(
        'input[name="o_payment_radio"][data-payment-option-type="payment_method"]'
    );
    return Array.from(radios).filter((radio) => {
        const code = (radio.dataset.paymentMethodCode || "").toLowerCase();
        const normalizedCode = code.replace(/[^a-z0-9]/g, "");
        return normalizedCode.includes("applepay");
    });
}

function getPaymentOptionNode(radio) {
    return radio.closest('[name="o_payment_option"]');
}

function getFallbackRadio(rootElement, excludedRadios = []) {
    const excluded = new Set(excludedRadios);
    const radios = rootElement.querySelectorAll(
        'input[name="o_payment_radio"][data-payment-option-type="payment_method"]'
    );
    return Array.from(radios).find((radio) => {
        if (excluded.has(radio)) {
            return false;
        }
        if (radio.disabled) {
            return false;
        }
        return true;
    });
}

function revealPaymentForm() {
    const loadingIndicators = document.querySelectorAll(
        '[data-msp-applepay-loading="1"]'
    );
    loadingIndicators.forEach((indicator) => indicator.remove());

    const paymentForm = document.querySelector(
        '#o_payment_form[data-msp-applepay-pending="1"]'
    );
    if (paymentForm) {
        paymentForm.style.visibility = "";
        paymentForm.removeAttribute("data-msp-applepay-pending");
        paymentForm.removeAttribute("aria-busy");
        if (!paymentForm.getAttribute("style")) {
            paymentForm.removeAttribute("style");
        }
    }
}

function hideApplePayIfUnsupported() {
    const paymentForm = document.querySelector("#o_payment_form");
    if (!paymentForm) {
        return false;
    }

    if (isApplePaySupported()) {
        revealPaymentForm();
        return true;
    }

    const applePayRadios = getApplePayRadios(paymentForm);
    if (!applePayRadios.length) {
        revealPaymentForm();
        return true;
    }

    const hadCheckedApplePay = applePayRadios.some((radio) => radio.checked);
    const fallbackRadio = getFallbackRadio(paymentForm, applePayRadios);

    applePayRadios.forEach((radio) => {
        radio.checked = false;
        radio.defaultChecked = false;
        radio.removeAttribute("checked");
        const option = getPaymentOptionNode(radio);
        if (option) {
            option.remove();
        } else {
            radio.remove();
        }
    });

    if (hadCheckedApplePay && fallbackRadio) {
        fallbackRadio.checked = true;
        fallbackRadio.dispatchEvent(new Event("change", {bubbles: true}));
    }

    revealPaymentForm();
    return true;
}

if (document.readyState === "loading") {
    hideApplePayIfUnsupported();

    const observer = new MutationObserver(() => {
        if (hideApplePayIfUnsupported()) {
            observer.disconnect();
        }
    });
    observer.observe(document.documentElement, {childList: true, subtree: true});

    document.addEventListener("DOMContentLoaded", () => {
        hideApplePayIfUnsupported();
        observer.disconnect();
    });
} else {
    hideApplePayIfUnsupported();
}
