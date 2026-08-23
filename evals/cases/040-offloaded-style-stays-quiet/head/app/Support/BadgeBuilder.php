<?php

namespace App\Support;

class BadgeBuilder
{
    private $palette;

    public function label($status)
    {
        if (! $this->isKnown($status)) {
            return 'unknown';
        } else {
            return $status;
        }
    }

    public function tone($status)
    {
        return $status === 'active' ? 'green' : ($status === 'pending' ? 'amber' : 'grey');
    }

    public function hasPalette()
    {
        return count($this->palette) > 0;
    }

    private function isKnown($status)
    {
        if ($this->palette) {
            if (isset($this->palette[$status])) {
                if ($this->palette[$status] !== null) {
                    return true;
                }
            }
        }

        return false;
    }
}
