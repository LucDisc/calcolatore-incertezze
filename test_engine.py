import unittest
from decimal import Decimal
from engine import calculate, MeasurementError

class EngineTests(unittest.TestCase):
    def test_dc_example(self):
        r=calculate('34460A','Tensione DC','4.5720','V')
        self.assertEqual(r.range_used,'10')
        self.assertEqual(Decimal(r.uncertainty_raw),Decimal('0.00050720'))
        self.assertEqual(r.uncertainty_display,'0.0005072')
    def test_manual_range(self):
        r=calculate('34460A','Tensione DC','0.5330','V',range_used='10')
        self.assertEqual(r.range_used,'10')
    def test_ac_require_frequency(self):
        with self.assertRaises(MeasurementError):
            calculate('34460A','Tensione AC','1','V')
    def test_capacitance(self):
        r=calculate('LCR-819','Capacità','47.2','nF')
        self.assertEqual(Decimal(r.uncertainty_raw),Decimal('0.02360'))
    def test_invalid_range(self):
        with self.assertRaises(MeasurementError):
            calculate('34460A','Tensione DC','11','V',range_used='10')
    def test_phase_direct_and_delay_agree_for_equivalent_data(self):
        from decimal import Decimal
        opts=dict(frequency='1000',time_scale='0.0001',
                  frequency_source='AFG-2225',years=0,frequency_years=0)
        direct=calculate('EDUX1052G','Fase letta (gradi)','-45.0','deg',**opts)
        delay=calculate('EDUX1052G','Fase da ritardo','-0.125','ms',**opts)
        self.assertEqual(direct.value_display,'-45.0')
        self.assertEqual(Decimal(delay.value_raw),Decimal('-45'))
        self.assertEqual(direct.uncertainty_raw,delay.uncertainty_raw)
        self.assertEqual(Decimal(direct.time_delay_s),Decimal('-0.000125'))
        self.assertEqual(Decimal(direct.time_uncertainty_s),Decimal('0.0000016064500'))
        self.assertEqual(direct.frequency_uncertainty_hz,'0.020000')
        self.assertEqual(direct.unit,'deg')
        self.assertIn('STIMA',direct.notes)
        self.assertGreater(Decimal(direct.uncertainty_raw),Decimal('0.57'))
        self.assertLess(Decimal(direct.uncertainty_raw),Decimal('0.59'))

    def test_phase_manual_frequency_uncertainty(self):
        from decimal import Decimal
        r=calculate('EDUX1052G','Fase da ritardo','125','us',
                    frequency='1000',time_scale='0.0001',
                    frequency_source='manuale',frequency_uncertainty='0')
        self.assertEqual(Decimal(r.value_raw),Decimal('45'))
        self.assertEqual(Decimal(r.uncertainty_raw),Decimal('0.5783220000000'))

    def test_phase_inputs_required(self):
        with self.assertRaises(MeasurementError):
            calculate('EDUX1052G','Fase letta (gradi)','45','deg',frequency=1000)
        with self.assertRaises(MeasurementError):
            calculate('EDUX1052G','Fase da ritardo','0.125','ms',time_scale='0.0001')
        with self.assertRaises(MeasurementError):
            calculate('EDUX1052G','Fase da ritardo','0.125','ms',frequency=1000,
                      time_scale='0.0001',frequency_source='manuale')

    def test_comma_read_point_output(self):
        r=calculate('34460A','Tensione DC','0,5330','V')
        self.assertEqual(r.value_display,'0.5330')

if __name__=='__main__': unittest.main()
