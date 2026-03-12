/** @odoo-module **/

function isApplePaySupported() {
    if (typeof window.ApplePaySession === 'undefined') {
        return false;
    }
    if (typeof window.ApplePaySession.canMakePayments !== 'function') {
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
        const code = (radio.dataset.paymentMethodCode || '').toLowerCase();
        const normalizedCode = code.replace(/[^a-z0-9]/g, '');
        return normalizedCode.includes('applepay');
    });
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

function disableApplePayIfUnsupported() {
    const paymentForm = document.querySelector('#o_payment_form');
    if (!paymentForm) {
        return false;
    }

    if (isApplePaySupported()) {
        return true;
    }

    const applePayRadios = getApplePayRadios(paymentForm);
    if (!applePayRadios.length) {
        return true;
    }

    const hadCheckedApplePay = applePayRadios.some((radio) => radio.checked);
    const fallbackRadio = getFallbackRadio(paymentForm, applePayRadios);

    applePayRadios.forEach((radio) => {
        radio.checked = false;
        radio.defaultChecked = false;
        radio.removeAttribute('checked');
        radio.disabled = true;
        const option = radio.closest('[name="o_payment_option"]');
        option?.setAttribute('aria-disabled', 'true');
    });

    if (hadCheckedApplePay && fallbackRadio) {
        fallbackRadio.checked = true;
        fallbackRadio.dispatchEvent(new Event('change', { bubbles: true }));
    }

    return true;
}

function applyApplePayVisibility() {
    return disableApplePayIfUnsupported();
}

window.mspDisableApplePayIfUnsupported = disableApplePayIfUnsupported;
window.mspApplePayVisibilityLoaded = true;

if (document.readyState === 'loading') {
    applyApplePayVisibility();

    const observer = new MutationObserver(() => {
        if (applyApplePayVisibility()) {
            observer.disconnect();
        }
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });

    document.addEventListener('DOMContentLoaded', () => {
        applyApplePayVisibility();
        observer.disconnect();
    });
} else {
    applyApplePayVisibility();
}
