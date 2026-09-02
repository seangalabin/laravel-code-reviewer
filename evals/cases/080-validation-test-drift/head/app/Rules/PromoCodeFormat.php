<?php

declare(strict_types=1);

namespace App\Rules;

final class PromoCodeFormat
{
    public static function isValid(string $code): bool
    {
        return (bool) preg_match('/^[A-Z]{3}-\d{4}$/', $code);
    }
}
