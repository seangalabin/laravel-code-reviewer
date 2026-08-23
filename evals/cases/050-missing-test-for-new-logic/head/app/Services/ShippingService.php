<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\Order;

final class ShippingService
{
    private const FREE_SHIPPING_THRESHOLD_CENTS = 10000;
    private const RURAL_SURCHARGE_CENTS = 1500;
    private const STANDARD_CENTS = 800;

    public function describe(Order $order): string
    {
        return $order->reference;
    }

    public function calculateShippingCents(Order $order): int
    {
        if ($order->subtotal_cents >= self::FREE_SHIPPING_THRESHOLD_CENTS) {
            return 0;
        }

        if ($order->is_rural) {
            return self::RURAL_SURCHARGE_CENTS;
        }

        return self::STANDARD_CENTS;
    }
}
