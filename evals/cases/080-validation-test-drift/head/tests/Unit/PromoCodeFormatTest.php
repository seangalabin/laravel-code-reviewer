<?php

declare(strict_types=1);

use App\Rules\PromoCodeFormat;

it('accepts promo codes in the documented format', function (string $code) {
    expect(PromoCodeFormat::isValid($code))->toBeTrue();
})->with([
    'ABC-1234',
    'XYZ1234',
]);
