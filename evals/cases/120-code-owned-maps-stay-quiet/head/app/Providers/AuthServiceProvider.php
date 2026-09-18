<?php

declare(strict_types=1);

namespace App\Providers;

use App\Models\Invoice;
use App\Models\Order;
use App\Models\Shipment;
use App\Policies\InvoicePolicy;
use App\Policies\OrderPolicy;
use App\Policies\ShipmentPolicy;
use Illuminate\Foundation\Support\Providers\AuthServiceProvider as ServiceProvider;

final class AuthServiceProvider extends ServiceProvider
{
    /**
     * @var array<class-string, class-string>
     */
    protected array $policies = [
        Order::class => OrderPolicy::class,
        Invoice::class => InvoicePolicy::class,
        Shipment::class => ShipmentPolicy::class,
    ];

    public function boot(): void
    {
        $this->registerPolicies();
    }
}
