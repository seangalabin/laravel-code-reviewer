<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\Order;

final class ShippingService
{
    public function describe(Order $order): string
    {
        return $order->reference;
    }
}
