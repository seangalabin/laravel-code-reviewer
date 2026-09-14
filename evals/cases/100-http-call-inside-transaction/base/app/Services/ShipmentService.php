<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\Shipment;
use App\Repositories\ShipmentRepository;

final class ShipmentService
{
    public function __construct(private readonly ShipmentRepository $shipments)
    {
    }

    public function book(int $orderId, string $carrier): Shipment
    {
        return $this->shipments->create($orderId, $carrier);
    }
}
