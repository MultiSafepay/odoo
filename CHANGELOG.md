All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and the version number follows the community convention:
`odoo_major.odoo_minor.module_major.module_minor.module_patch`
(e.g. `18.0.1.0.0` = Odoo 18.1 + module v1.0.0), which also aligns
with [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

## [19.0.2.0.0] - 2026-02-18
### Changed
- ODOO-159: Refactor module structure by separating core and enhanced features, reducing dependencies

## [19.0.1.2.1] - 2026-01-22
### Added
- ODOO-173: Add error-level logging for failed MultiSafepay order requests

## [19.0.1.2.0] - 2025-12-01
### Added
- ODOO-122: Add pricelist filter to payment method list (#1)

### Changed
- ODOO-155: Refactor cleanup logic preserving user configuration (#3)

### Fixed
- ODOO-162: Fix installation instructions in README.md file (#6)

## [19.0.1.1.0] - 2025-10-31
### Added
- ODOO-123: Refund reason field for better transaction tracking

### Fixed
- ODOO-147: Webhook validation issues for improved reliability
- ODOO-131: Floating-point arithmetic calculation error for accurate financial calculations
- ODOO-147: Precise calculation implementation in all cases to ensure accuracy
- ODOO-132: Unnecessary filter removal from code for better performance

## [19.0.1.0.0] - 2025-10-24
### Added
- Add support for Odoo 19.0.
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
