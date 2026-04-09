<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <!-- Budget Slider -->
    <div class="card budget-card">
      <div class="budget-controls">
        <div class="budget-label-row">
          <label class="budget-label">{{ t('restocking.budgetLabel') }}</label>
          <span class="budget-value">{{ formatCurrency(budget) }}</span>
        </div>
        <input
          type="range"
          class="budget-slider"
          :min="1000"
          :max="50000"
          :step="1000"
          v-model.number="budget"
        />
        <div class="budget-range-labels">
          <span>{{ formatCurrency(1000) }}</span>
          <span class="budget-help">{{ t('restocking.budgetHelp') }}</span>
          <span>{{ formatCurrency(50000) }}</span>
        </div>
      </div>
    </div>

    <!-- Stats Cards -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">{{ t('restocking.statsItems') }}</div>
        <div class="stat-value">{{ recommendations.length }}</div>
      </div>
      <div class="stat-card" :class="overBudget ? 'danger' : 'success'">
        <div class="stat-label">{{ t('restocking.statsCost') }}</div>
        <div class="stat-value">{{ formatCurrency(totalEstimatedCost) }}</div>
      </div>
      <div class="stat-card" :class="budgetRemaining < 0 ? 'danger' : 'success'">
        <div class="stat-label">{{ t('restocking.statsBudgetRemaining') }}</div>
        <div class="stat-value">{{ formatCurrency(budgetRemaining) }}</div>
      </div>
    </div>

    <!-- Loading / Error -->
    <div v-if="loading" class="loading">{{ t('restocking.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>

    <!-- Success Banner -->
    <div v-if="orderSuccess" class="success-banner">
      <div class="success-content">
        <strong>{{ t('restocking.orderSuccess') }}</strong>
        <span>{{ t('restocking.orderSuccessDetail', { orderNumber: orderSuccess.order_number }) }}</span>
        <router-link to="/orders" class="success-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>
    </div>

    <!-- Recommendations Table -->
    <div v-if="!loading && !error" class="card">
      <div class="card-header">
        <h3 class="card-title">{{ t('restocking.tableTitle') }}</h3>
        <span v-if="overBudget" class="badge danger">{{ t('restocking.overBudget') }}</span>
      </div>

      <div v-if="recommendations.length === 0" class="empty-state">
        {{ t('restocking.noRecommendations') }}
      </div>

      <div v-else>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.colSku') }}</th>
                <th>{{ t('restocking.colName') }}</th>
                <th>{{ t('restocking.colTrend') }}</th>
                <th>{{ t('restocking.colDemandGap') }}</th>
                <th>{{ t('restocking.colUnitCost') }}</th>
                <th>{{ t('restocking.colQty') }}</th>
                <th>{{ t('restocking.colLineCost') }}</th>
                <th>{{ t('restocking.colInclude') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in recommendations"
                :key="item.item_sku"
                :class="{ 'row-excluded': !getRowState(item.item_sku).checked }"
              >
                <td><strong>{{ item.item_sku }}</strong></td>
                <td>{{ item.item_name }}</td>
                <td>
                  <span :class="['badge', item.trend]">
                    {{ t(`trends.${item.trend}`) }}
                  </span>
                </td>
                <td class="demand-gap">+{{ item.gap }}</td>
                <td>{{ formatUnitCost(item.unit_cost) }}</td>
                <td>
                  <input
                    type="number"
                    class="qty-input"
                    :min="1"
                    :value="getRowState(item.item_sku).qty"
                    @input="updateQty(item.item_sku, $event.target.value)"
                  />
                </td>
                <td class="line-cost">
                  {{ formatCurrency(getLineCost(item.item_sku, item.unit_cost)) }}
                </td>
                <td>
                  <input
                    type="checkbox"
                    class="include-checkbox"
                    :checked="getRowState(item.item_sku).checked"
                    @change="toggleChecked(item.item_sku)"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Running Total Bar -->
        <div class="running-total-bar">
          <div class="running-total-info">
            <span class="running-total-label">{{ t('restocking.runningTotal') }}:</span>
            <span class="running-total-value" :class="overBudget ? 'over' : 'under'">
              {{ formatCurrency(selectedCost) }}
            </span>
            <span class="running-total-of">{{ t('restocking.budgetOf') }}</span>
            <span class="running-total-budget">{{ formatCurrency(budget) }}</span>
          </div>
          <div class="progress-track">
            <div
              class="progress-fill"
              :class="overBudget ? 'over-budget' : 'under-budget'"
              :style="{ width: progressWidth }"
            ></div>
          </div>
        </div>

        <!-- Place Order -->
        <div class="order-actions">
          <button
            class="place-order-btn"
            :disabled="!canPlaceOrder || submitting"
            @click="placeOrder"
          >
            {{ submitting ? '...' : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="submitError" class="error">{{ submitError }}</div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()

    const budget = ref(25000)
    const recommendations = ref([])
    const loading = ref(false)
    const error = ref(null)
    const submitting = ref(false)
    const submitError = ref(null)
    const orderSuccess = ref(null)

    // Per-row state: keyed by sku, stores { qty, checked }
    const rowState = ref({})

    const initRowState = (items) => {
      const state = {}
      for (const item of items) {
        // Preserve existing state if user already edited, else initialize from API
        const existing = rowState.value[item.item_sku]
        state[item.item_sku] = {
          qty: existing ? existing.qty : item.restock_quantity,
          checked: existing !== undefined ? existing.checked : true
        }
      }
      rowState.value = state
    }

    const getRowState = (sku) => {
      return rowState.value[sku] || { qty: 0, checked: true }
    }

    const updateQty = (sku, rawValue) => {
      const qty = Math.max(1, parseInt(rawValue, 10) || 1)
      if (rowState.value[sku]) {
        rowState.value[sku] = { ...rowState.value[sku], qty }
      }
    }

    const toggleChecked = (sku) => {
      if (rowState.value[sku]) {
        rowState.value[sku] = { ...rowState.value[sku], checked: !rowState.value[sku].checked }
      }
    }

    const getLineCost = (sku, unitCost) => {
      const state = getRowState(sku)
      return state.qty * unitCost
    }

    // Total estimated cost = sum of all recommended items at their default restock_cost
    const totalEstimatedCost = computed(() => {
      return recommendations.value.reduce((sum, item) => sum + item.restock_cost, 0)
    })

    // Selected cost = sum of checked items at current qty
    const selectedCost = computed(() => {
      return recommendations.value.reduce((sum, item) => {
        const state = getRowState(item.item_sku)
        if (!state.checked) return sum
        return sum + getLineCost(item.item_sku, item.unit_cost)
      }, 0)
    })

    const budgetRemaining = computed(() => budget.value - selectedCost.value)

    const overBudget = computed(() => selectedCost.value > budget.value)

    // Progress bar capped at 100% visually, but reflects over-budget via color
    const progressWidth = computed(() => {
      if (budget.value === 0) return '0%'
      const pct = Math.min((selectedCost.value / budget.value) * 100, 100)
      return `${pct.toFixed(1)}%`
    })

    const canPlaceOrder = computed(() => {
      if (overBudget.value) return false
      return recommendations.value.some(item => getRowState(item.item_sku).checked)
    })

    const loadRecommendations = async () => {
      loading.value = true
      error.value = null
      orderSuccess.value = null
      try {
        const data = await api.getRestockingRecommendations(budget.value)
        recommendations.value = data
        initRowState(data)
      } catch (err) {
        error.value = 'Failed to load restocking recommendations'
        console.error(err)
      } finally {
        loading.value = false
      }
    }

    // Reload when budget changes
    watch(budget, () => {
      loadRecommendations()
    })

    const formatCurrency = (value) => {
      if (currentCurrency.value === 'JPY') {
        return new Intl.NumberFormat('ja-JP', { style: 'currency', currency: 'JPY', maximumFractionDigits: 0 }).format(value)
      }
      return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
    }

    const formatUnitCost = (value) => {
      if (currentCurrency.value === 'JPY') {
        return new Intl.NumberFormat('ja-JP', { style: 'currency', currency: 'JPY', maximumFractionDigits: 0 }).format(value)
      }
      return `$${value.toFixed(2)}`
    }

    const placeOrder = async () => {
      if (!canPlaceOrder.value || submitting.value) return
      submitting.value = true
      submitError.value = null
      orderSuccess.value = null

      try {
        const checkedItems = recommendations.value
          .filter(item => getRowState(item.item_sku).checked)
          .map(item => ({
            sku: item.item_sku,
            name: item.item_name,
            quantity: getRowState(item.item_sku).qty,
            unit_cost: item.unit_cost
          }))

        const result = await api.submitRestockingOrder({
          items: checkedItems,
          total_budget: budget.value
        })
        orderSuccess.value = result
      } catch (err) {
        submitError.value = 'Failed to submit order. Please try again.'
        console.error(err)
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadRecommendations)

    return {
      t,
      budget,
      recommendations,
      loading,
      error,
      submitting,
      submitError,
      orderSuccess,
      rowState,
      getRowState,
      updateQty,
      toggleChecked,
      getLineCost,
      totalEstimatedCost,
      selectedCost,
      budgetRemaining,
      overBudget,
      progressWidth,
      canPlaceOrder,
      formatCurrency,
      formatUnitCost,
      placeOrder
    }
  }
}
</script>

<style scoped>
/* Budget Card */
.budget-card {
  margin-bottom: 1.25rem;
}

.budget-controls {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.budget-label-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.budget-slider {
  width: 100%;
  height: 6px;
  -webkit-appearance: none;
  appearance: none;
  background: #e2e8f0;
  border-radius: 3px;
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  cursor: pointer;
  border: 2px solid #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
  transition: background 0.2s;
}

.budget-slider::-webkit-slider-thumb:hover {
  background: #1d4ed8;
}

.budget-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  cursor: pointer;
  border: 2px solid #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
}

.budget-range-labels {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.75rem;
  color: #94a3b8;
}

.budget-help {
  color: #94a3b8;
  font-style: italic;
}

/* Table row states */
.row-excluded td {
  opacity: 0.45;
}

.demand-gap {
  color: #059669;
  font-weight: 600;
}

.line-cost {
  font-weight: 600;
  color: #0f172a;
}

/* Qty input */
.qty-input {
  width: 72px;
  padding: 0.375rem 0.5rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.875rem;
  color: #0f172a;
  text-align: center;
  outline: none;
  transition: border-color 0.15s;
}

.qty-input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1);
}

/* Include checkbox */
.include-checkbox {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: #2563eb;
}

/* Running total bar */
.running-total-bar {
  margin-top: 1.25rem;
  padding: 1rem 1.25rem;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  border-radius: 0 0 8px 8px;
}

.running-total-info {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  margin-bottom: 0.625rem;
  font-size: 0.938rem;
}

.running-total-label {
  font-weight: 600;
  color: #475569;
}

.running-total-value {
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: -0.025em;
}

.running-total-value.under {
  color: #059669;
}

.running-total-value.over {
  color: #dc2626;
}

.running-total-of {
  color: #94a3b8;
}

.running-total-budget {
  font-weight: 600;
  color: #0f172a;
}

.progress-track {
  width: 100%;
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease, background-color 0.3s ease;
}

.progress-fill.under-budget {
  background: #10b981;
}

.progress-fill.over-budget {
  background: #ef4444;
}

/* Order actions */
.order-actions {
  display: flex;
  justify-content: flex-end;
  padding: 1rem 1.25rem 0;
}

.place-order-btn {
  padding: 0.625rem 1.75rem;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s, opacity 0.2s;
}

.place-order-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.place-order-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* Success banner */
.success-banner {
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 1.25rem;
}

.success-content {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  font-size: 0.938rem;
  color: #065f46;
}

.success-link {
  color: #065f46;
  font-weight: 600;
  text-decoration: underline;
  margin-left: auto;
}

.success-link:hover {
  color: #047857;
}

/* Empty state */
.empty-state {
  text-align: center;
  padding: 3rem;
  color: #64748b;
  font-size: 0.938rem;
}
</style>
