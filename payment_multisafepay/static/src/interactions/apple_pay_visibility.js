/** @odoo-module **/

import { Interaction } from '@web/public/interaction';
import { registry } from '@web/core/registry';

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

export class ApplePayVisibility extends Interaction {
    static selector = '#o_payment_form';

    async willStart() {
        if (isApplePaySupported()) {
            return;
        }
        const applePayRadios = getApplePayRadios(this.el);
        if (!applePayRadios.length) {
            return;
        }
        const hadCheckedApplePay = applePayRadios.some((r) => r.checked);
        const fallbackRadio = getFallbackRadio(this.el, applePayRadios);

        applePayRadios.forEach((radio) => {
            radio.checked = false;
            radio.defaultChecked = false;
            radio.removeAttribute('checked');
            const option = getPaymentOptionNode(radio);
            if (option) {
                option.remove();
            } else {
                radio.remove();
            }
        });

        if (hadCheckedApplePay && fallbackRadio) {
            fallbackRadio.checked = true;
            fallbackRadio.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    start() {
        document.querySelectorAll('[data-msp-applepay-loading="1"]').forEach((el) => el.remove());
        this.el.style.display = '';
        this.el.style.visibility = '';
        this.el.removeAttribute('data-msp-applepay-pending');
        this.el.removeAttribute('aria-busy');
        if (!this.el.getAttribute('style')) {
            this.el.removeAttribute('style');
        }
    }
}

registry.category('public.interactions').add(
    'payment_multisafepay.ApplePayVisibility',
    ApplePayVisibility
);
