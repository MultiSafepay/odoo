All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and the version number follows the community convention:
`odoo_major.odoo_minor.module_major.module_minor.module_patch`
(e.g. `18.0.1.0.0` = Odoo 18.1 + module v1.0.0), which also aligns
with [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

## [19.0.2.4.0] - 2026-07-24

### Added
- ODOO-256: Add optional shopping cart and restrict BNPL payment methods to this new setting field

### Changed
- ODOO-259: Upgrade Python SDK dependency

### Fixed
- ODOO-255: Fix miscalculation of total amount in shopping cart, within the order request, when using multiple tax rates

## [18.0.2.3.0] - 2026-07-14
### Added
- ODOO-248: Add Validate Shopping Cart setting field

## [18.0.2.2.1] - 2026-06-17
### Fixed
- ODOO-232: Fix t-if clause avoiding incorrect nested if statements
- ODOO-229: Multi-website: payment options URLs always use global web.base.url instead of per-website domain

## [18.0.2.2.0] - 2026-04-21
### Added
- ODOO-146: Add Apple Pay visibility script and register asset

### Fixed
- ODOO-190: Support partial payment links and minor units

## [18.0.2.1.2] - 2026-03-18
### Fixed
- ODOO-204: Use state_message kwarg for state setters

## [18.0.2.1.1] - 2026-03-12
### Fixed
- ODOO-199: Fix shopping cart unit prices when taxes are configured as "Price Included"
- ODOO-198: Fix shop version, within MultiSafepay order request

## [18.0.2.1.0] - 2026-03-10
### Changed
- ODOO-188: Use RequestsTransport with custom session

## [18.0.2.0.0] - 2026-02-18
### Changed
- ODOO-160: Refactor module structure by separating core and enhanced features, reducing dependencies

## [18.0.1.3.1] - 2026-01-22
### Added
- ODOO-174: Add error-level logging for failed MultiSafepay order requests

## [18.0.1.3.0] - 2025-12-01
### Added
- ODOO-154: Add pricelist filter to payment method list

### Changed
- ODOO-156: Refactor cleanup logic preserving user configuration

### Fixed
- ODOO-164: Fix installation instructions in README.md file

## [18.0.1.2.0] - 2025-10-31
### Added
- ODOO-135: Refund reason field for better transaction tracking

### Fixed
- ODOO-148: Webhook validation issues for improved reliability
- ODOO-134: Floating-point arithmetic calculation error for accurate financial calculations
- ODOO-137: Incorrect decimal precision in calculations for better accuracy
- ODOO-136: Unnecessary filter removal from code for better performance

## [18.0.1.1.0] - 2025-10-24
### Added
- HTTP GET method support in webhook endpoint for improved integration flexibility
- Enhanced logging functionality across multiple modules for better debugging and monitoring

### Changed
- Enabled cart validation in Order Request for better transaction integrity

### Fixed
- Resolved duplicated merchant item ID issue in buy_x_get_y promotions
- Corrected unclear transaction status mapping for better transaction tracking
- Fixed inconsistencies in provider configuration management

## [18.0.1.0.0] - 2025-09-15
### Added
- Compatibility with Odoo 18.0.
- Support for MultiSafepay payment methods.
- Support for partial and full refunds.
- Ability to mark MultiSafepay transactions as shipped when items are delivered.
